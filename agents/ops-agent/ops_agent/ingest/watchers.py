"""Background sources, run by one ingest replica at a time (Postgres advisory lock): Kubernetes Warning events, the
change tracker (merges to main from a read-only clone, Argo CD syncs), the docs index, and the GitHub poller (only
when a read-only token exists)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import subprocess
from pathlib import Path

import httpx

from .. import db
from ..config import settings
from ..correlate import components_for_paths, from_k8s_event, parse_time
from ..tools import docs

log = logging.getLogger("ops-ingest.watch")
SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
API = "https://kubernetes.default.svc"


def _k8s() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=API, verify=str(SA / "ca.crt"),
                             headers={"Authorization": "Bearer " + (SA / "token").read_text().strip()},
                             timeout=httpx.Timeout(10, read=330))


async def k8s_events(handle) -> None:
    """Watch Warning events cluster-wide; only events newer than the watch start count."""
    started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)
    while True:
        try:
            async with _k8s() as c:
                lst = (await c.get("/api/v1/events", params={"fieldSelector": "type=Warning", "limit": 1})).json()
                rv = lst["metadata"]["resourceVersion"]
                async with c.stream("GET", "/api/v1/events", params={"watch": "1", "fieldSelector": "type=Warning",
                                                                     "resourceVersion": rv, "timeoutSeconds": 300}) as r:
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        obj = json.loads(line).get("object", {})
                        ev = from_k8s_event(obj)
                        if ev and ev.occurred_at >= started:
                            await handle(ev)
        except Exception as e:
            log.warning("k8s watch: %s", e)
        await asyncio.sleep(5)


def _key_copy() -> str:
    """OpenSSH refuses a key that its group can read (Secret volumes are 0440 for fsGroup): use a 0600 copy in tmp."""
    s = settings()
    dst = Path("/tmp/ops-agent-deploy-key")
    if not dst.exists():
        dst.write_bytes(Path(s.deploy_key_file).read_bytes())
        dst.chmod(0o600)
    return str(dst)


def _git(*args: str) -> str:
    s = settings()
    env = dict(os.environ, GIT_SSH_COMMAND=f"ssh -i {_key_copy()} -o IdentitiesOnly=yes "
                                           f"-o UserKnownHostsFile={s.opsro_known_hosts} -o StrictHostKeyChecking=yes")
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, env=env, timeout=120).stdout


def sync_repo() -> str | None:
    s = settings()
    if not Path(s.deploy_key_file).exists():
        return None
    repo = Path(s.repo_dir)
    if not (repo / "HEAD").exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--bare", "--filter=blob:none", "--single-branch", "--branch", "main", s.repo_url, str(repo))
    _git("-C", str(repo), "fetch", "--prune", "origin", "+refs/heads/main:refs/heads/main")
    return _git("-C", str(repo), "rev-parse", "main").strip()


def record_merges(days: int = 14) -> int:
    s = settings()
    out = _git("-C", s.repo_dir, "log", "main", "--first-parent", f"--since={days}.days", "--name-only",
               "--format=@@%H%x09%cI%x09%s")
    n = 0
    for block in out.split("@@")[1:]:
        head, *paths = [l for l in block.splitlines() if l.strip()]
        sha, when, subject = head.split("\t", 2)
        db.run("INSERT INTO changes (at, kind, ref, summary, paths, components) VALUES (%s,'merge',%s,%s,%s,%s) "
               "ON CONFLICT (kind, ref) DO NOTHING", parse_time(when), sha, subject[:300], paths[:200],
               components_for_paths(paths))
        n += 1
    return n


async def record_syncs() -> int:
    n = 0
    async with _k8s() as c:
        apps = (await c.get("/apis/argoproj.io/v1alpha1/namespaces/argocd/applications")).json().get("items", [])
    for a in apps:
        name = a["metadata"]["name"]
        path = (a.get("spec", {}).get("source") or {}).get("path", "")
        for h in (a.get("status", {}).get("history") or [])[-10:]:
            if not h.get("deployedAt"):
                continue
            ref = f"{name}@{(h.get('revision') or '')[:12]}@{h.get('id')}"
            db.run("INSERT INTO changes (at, kind, ref, summary, paths, components) VALUES (%s,'argocd-sync',%s,%s,%s,%s) "
                   "ON CONFLICT (kind, ref) DO NOTHING", parse_time(h["deployedAt"]), ref,
                   f"Argo CD synced {name} to {(h.get('revision') or '')[:12]}", [path], components_for_paths([path]) or [name])
            n += 1
    return n


async def changes_and_docs() -> None:
    last = None
    while True:
        try:
            head = await asyncio.to_thread(sync_repo)
            if head and head != last:
                await asyncio.to_thread(record_merges)
                k = await asyncio.to_thread(docs.index_commit, settings().repo_dir, head)
                db.run("DELETE FROM docs_chunks WHERE commit <> %s AND commit NOT IN (SELECT DISTINCT commit FROM docs_chunks "
                       "WHERE id > (SELECT coalesce(max(id), 0) - 50000 FROM docs_chunks)) ", head)
                log.info("repo at %s: %d doc chunks indexed", head[:12], k)
                last = head
            await record_syncs()
        except Exception as e:
            log.warning("changes/docs: %s", e)
        await asyncio.sleep(300)


async def github_runs(handle) -> None:
    """Failed Actions runs, classified (decision 0013 Q14: in shadow mode only reported). Off without a token."""
    from ..correlate import Event
    s = settings()
    headers = {"Accept": "application/vnd.github+json"}
    if s.github_token:
        headers["Authorization"] = "Bearer " + s.github_token
    seen: set[int] = set()
    started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=15)   # no incidents for old failures at start
    async with httpx.AsyncClient(base_url="https://api.github.com", timeout=30, headers=headers) as gh:
        # A public repo needs no token (60 requests/hour unauthenticated: one list every 5 min plus the jobs of new
        # failures). A private repo without a token: the API says 404 and the poller stays off (decision 0013 Q1).
        probe = await gh.get(f"/repos/{s.github_repo}/actions/runs", params={"per_page": 1})
        if probe.status_code != 200:
            log.info("GitHub poller off: HTTP %s without a read token", probe.status_code)
            return
        while True:
            try:
                runs = (await gh.get(f"/repos/{s.github_repo}/actions/runs", params={"per_page": 30})).json().get("workflow_runs", [])
                for r in runs:
                    if r["id"] in seen or r.get("status") != "completed" or r.get("conclusion") not in ("failure", "startup_failure", "timed_out"):
                        continue
                    if parse_time(r.get("updated_at")) < started:
                        seen.add(r["id"])
                        continue
                    seen.add(r["id"])
                    jobs = (await gh.get(f"/repos/{s.github_repo}/actions/runs/{r['id']}/jobs")).json().get("jobs", [])
                    steps = sum(len(j.get("steps") or []) for j in jobs)
                    klass = "infra" if r["conclusion"] == "startup_failure" or steps == 0 else "check"
                    if klass == "check" and r.get("head_branch") != "main":
                        continue   # a red check on a PR branch is the PR's business; infra failures count everywhere
                    await handle(Event(source="github", occurred_at=parse_time(r.get("updated_at")),
                                       fingerprint=f"gh-{r['id']}", status="firing",
                                       summary=f"CI {r['name']} {r['conclusion']} on {r.get('head_branch')} ({klass}; {steps} steps)",
                                       labels={"workflow": r["name"], "failure_class": klass, "run_id": str(r["id"]),
                                               "branch": r.get("head_branch", "")},
                                       payload={"html_url": r.get("html_url"), "event": r.get("event")}, klass="ci"))
            except Exception as e:
                log.warning("github: %s", e)
            await asyncio.sleep(300)
