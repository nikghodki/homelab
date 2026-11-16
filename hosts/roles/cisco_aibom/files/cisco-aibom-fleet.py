#!/usr/bin/env python3
"""Nightly Cisco AIBOM of one host: scan its agent code dirs and AI container images, keep the JSON, log the diff.
Optionally it also scans other hosts' images by digest (`remote_images`), so a small host needn't run image scans:
those results are written and logged as the other host's (`host`), with `scanned_on` set to this host.

Reads a targets file (roles/cisco_aibom/templates/targets.json.j2), runs `cisco-aibom analyze` once per target,
writes <state>/<host>-<date>.json (kept `keep_days` days) and prints journal lines (SyslogIdentifier cisco-aibom)
that the host collector ships to Loki:
  {"event": "aibom", ...}          one summary per run: component counts per type and per target, added/removed
  {"event": "aibom.new", ...}      one per component that was not in the previous run (capped)
  {"event": "aibom.removed", ...}  one per component that is gone (capped)
  {"event": "aibom.skipped", "reason": "skipped: low memory", ...}  an image target not scanned because MemAvailable
                                   was below its threshold (image_min_mem_gib / image_min_mem_gib_by_container, keyed by container
                                   or remote image name)
Secret findings are counted, never named. The agentic stage uses LiteLLM when /etc/cisco-aibom/llm.env exists
(runbooks/aibom.md), else the BOM is deterministic-only.
Managed by homelab Ansible (roles/cisco_aibom). Usage: cisco-aibom-fleet <targets.json>
"""
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

MAX_LINES = 50          # per-component journal lines per run and direction
HIDDEN_TYPES = {"secret"}
# `analyze` insists on an LLM. None is reachable on purpose: a closed port makes it fall back to its deterministic
# scanners at once (agentic_status "degraded").
NO_LLM = ["--llm-model", "none", "--llm-provider", "openai", "--llm-api-base", "http://127.0.0.1:9",
          "--llm-api-key", "unused", "--agentic-max-retry-seconds", "0", "--agentic-timeout", "5"]


def llm_args(environ=os.environ) -> list[str]:
    """The LLM comes from AIBOM_LLM_* (the root-only /etc/cisco-aibom/llm.env, read by cisco-aibom itself, so the key
    never shows up in the process list). Without a base URL and key: the closed port above, deterministic-only."""
    if environ.get("AIBOM_LLM_API_BASE") and environ.get("AIBOM_LLM_API_KEY"):
        return ["--agentic-timeout", environ.get("AIBOM_AGENTIC_TIMEOUT", "900"), "--agentic-concurrency", "1"]
    return NO_LLM


def log(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def mem_available_gib() -> float:
    """MemAvailable from /proc/meminfo, in GiB (on a DGX Spark this is the unified CPU+GPU memory left)."""
    with open("/proc/meminfo", encoding="ascii") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    raise RuntimeError("no MemAvailable in /proc/meminfo")


def image_of(container: str) -> str:
    """The image reference a running container was started from (tag or digest), via the Docker CLI."""
    out = subprocess.run(["docker", "inspect", "-f", "{{.Config.Image}}", container],
                         capture_output=True, text=True, timeout=60, check=False)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"container {container} not found: {out.stderr.strip()[-200:]}")
    return out.stdout.strip()


def docker(*args: str, timeout: int = 600) -> str:
    out = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {out.stderr.strip()[-200:]}")
    return out.stdout.strip()


def copy_app_dirs(image: str, dest: pathlib.Path, extra: list | tuple = ()) -> list[str]:
    """Fallback when cisco-aibom's `docker save` discovery fails (Docker's containerd image store drops the
    compressed layers after unpacking): copy the image's working dir, the usual app dirs and `extra` (per target,
    e.g. /usr/src/homeassistant) out of a created, never started, container, the way cisco-aibom's own create+cp
    extraction does."""
    wd = docker("image", "inspect", "-f", "{{.Config.WorkingDir}}", image) or "/"
    wanted = [d for d in dict.fromkeys([wd, "/app", "/opt", "/srv", *extra]) if d != "/"]
    cid = docker("create", image)
    copied = []
    try:
        for d in wanted:
            target = dest / d.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                docker("cp", f"{cid}:{d}", str(target))
                copied.append(d)
            except RuntimeError:
                pass  # not in this image
    finally:
        docker("rm", cid)
    return copied


def scan(exe: str, source: str, is_image: bool, timeout: int, workdir: pathlib.Path) -> dict:
    out = workdir / "report.json"
    out.unlink(missing_ok=True)
    cmd = [exe, "analyze", source, "-o", "json", "-O", str(out), "--no-progress", "--no-show-summary",
           "--cache-dir", str(workdir / "cache"), *llm_args()]
    if is_image:
        cmd += ["--container-extraction-tier", "docker"]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, cwd=workdir)
    if run.returncode != 0 or not out.exists():
        raise RuntimeError(f"cisco-aibom exit {run.returncode}: {run.stderr.strip()[-300:]}")
    report = json.loads(out.read_text())["aibom_analysis"]
    if (report.get("metadata") or {}).get("status") == "failed" or not report.get("sources"):
        raise RuntimeError("; ".join(map(str, report.get("errors") or ["no sources analysed"]))[-300:])
    return report


def components(target: str, report: dict) -> set[tuple[str, str, str, str]]:
    """(target, type, name, file) for every component of a report; file is relative to the scanned source."""
    out = set()
    for src in (report.get("sources") or {}).values():
        root = str(src.get("source_path") or "")
        for ctype, items in (src.get("components") or {}).items():
            for c in items or []:
                path = str(c.get("file_path") or "")
                if root and path.startswith(root):
                    path = path[len(root):].lstrip("/")
                out.add((target, ctype, str(c.get("name") or c.get("model_name") or "?"), path))
    return out


def counts(items: set) -> tuple[dict, dict]:
    by_type, by_target = {}, {}
    for target, ctype, _, _ in items:
        by_type[ctype] = by_type.get(ctype, 0) + 1
        by_target[target] = by_target.get(target, 0) + 1
    return dict(sorted(by_type.items())), dict(sorted(by_target.items()))


def load_components(doc: dict) -> set:
    return {c for name, t in (doc.get("targets") or {}).items() if t.get("report")
            for c in components(name, t["report"])}


def baseline(paths: list, names: set) -> set:
    """Per target, the components of the latest previous run in which it was scanned, so a target that was
    skipped or failed on some night is compared with its last real scan, not counted as all added."""
    out, todo = set(), set(names)
    for p in reversed(paths):
        if not todo:
            break
        targets = json.loads(p.read_text()).get("targets") or {}
        for name in sorted(todo):
            t = targets.get(name)
            if t and t.get("report"):
                out |= components(name, t["report"])
                todo.discard(name)
    return out


def changes(event: str, host: str, items: set, extra: dict | None = None) -> None:
    for target, ctype, name, path in sorted(items)[:MAX_LINES]:
        if ctype in HIDDEN_TYPES:
            name = "(secret)"
        log(event, host=host, target=target, type=ctype, name=name, file=path, **(extra or {}))


def ensure_image(ref: str) -> bool:
    """Make a digest-pinned image present locally; True if this call pulled it."""
    try:
        docker("image", "inspect", "-f", "{{.Id}}", ref, timeout=60)
        return False
    except RuntimeError:
        docker("pull", "--quiet", ref, timeout=1800)
        return True


def prune_remote_images(state: pathlib.Path, wanted: set, pulled: set) -> None:
    """Remove images this job pulled on an earlier night that are no longer configured; remember what it pulled."""
    book = state / "remote-images.json"
    ours = set(json.loads(book.read_text())) if book.exists() else set()
    ours |= pulled
    for ref in sorted(ours - wanted):
        try:
            docker("image", "rm", ref, timeout=300)
        except RuntimeError:
            pass  # already gone, or used by a container (then it is not ours to remove)
    book.write_text(json.dumps(sorted(ours & wanted)))


def scan_target(cfg: dict, host: str, name: str, source: str, kind: str, opts: dict, work: pathlib.Path,
                pulled: set) -> dict:
    """Scan one target into an entry ({"status": ok | skipped, ...}; errors raise). kind: dir | container | image."""
    entry = {"kind": "dir" if kind == "dir" else "image"}
    is_image = kind != "dir"
    if is_image:
        min_gib_by = cfg.get("image_min_mem_gib_by_container") or {}
        need = float(min_gib_by.get(opts.get("key", source), cfg.get("image_min_mem_gib", 0)))
        avail = mem_available_gib() if need > 0 else None
        if avail is not None and avail < need:
            entry["container" if kind == "container" else "image"] = source
            entry.update(status="skipped", reason="low memory", mem_available_gib=round(avail, 1), need_gib=need)
            log("aibom.skipped", host=host, target=name, reason="skipped: low memory",
                mem_available_gib=round(avail, 1), need_gib=need, **opts.get("log", {}))
            return entry
    if kind == "container":
        entry["container"], source = source, image_of(source)
    elif kind == "image":
        # another host's image, scanned here by digest so the small host doesn't pay for it (runbooks/aibom.md)
        if "@sha256:" not in source:
            raise RuntimeError(f"{source}: remote images must be pinned by digest")
        entry["image"] = source
        if ensure_image(source):
            pulled.add(source)
    elif not os.path.isdir(source):
        raise RuntimeError(f"{source} does not exist")
    entry["source"] = source
    timeout = int(cfg.get("timeout_s", 3600))
    try:
        entry["report"] = scan(cfg["exe"], source, is_image, timeout, work)
        entry["method"] = "aibom-container" if is_image else "dir"
    except RuntimeError as e:
        if not (is_image and "discovery failed" in str(e)):
            raise
        app = work / "image-app"
        shutil.rmtree(app, ignore_errors=True)
        entry["copied"] = copy_app_dirs(source, app, opts.get("paths") or [])
        entry["report"] = scan(cfg["exe"], str(app), False, timeout, work)
        entry["method"] = "docker-cp-fallback"
        shutil.rmtree(app, ignore_errors=True)
    entry["status"] = "ok"
    return entry


def run_host(cfg: dict, host: str, targets: list, state: pathlib.Path, work: pathlib.Path, pulled: set,
             scanned_on: str | None = None) -> list:
    """Scan one host's targets, write <state>/<host>-<date>.json, log the summary and the diff; return the errors.
    scanned_on is set when the targets belong to another host (its images, scanned here)."""
    extra = {"scanned_on": scanned_on} if scanned_on else {}
    doc = {"host": host, **extra,
           "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "targets": {}}
    errors, skipped = [], []
    for name, source, kind, opts in targets:
        try:
            entry = scan_target(cfg, host, name, source, kind, {**opts, "log": extra}, work, pulled)
            if entry["status"] == "skipped":
                skipped.append(name)
        except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError) as e:
            entry = {"kind": "dir" if kind == "dir" else "image", "status": "error", "error": str(e)[-300:]}
            errors.append(f"{name}: {entry['error']}")
        doc["targets"][name] = entry
    doc["finished"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    today = state / f"{host}-{datetime.date.today().isoformat()}.json"
    previous = [p for p in sorted(state.glob(f"{host}-*.json")) if p != today]
    today.write_text(json.dumps(doc, indent=1))
    now = load_components(doc)
    by_type, by_target = counts(now)
    summary = {"host": host, **extra, "total": len(now), "counts": by_type, "targets": by_target,
               "errors": errors, "skipped": skipped, "agentic": "off"}
    if previous:
        last_doc = json.loads(previous[-1].read_text())
        not_scanned = {n for n, t in doc["targets"].items() if t.get("status") != "ok"}
        # a target that failed or was skipped tonight is not "removed": compare only targets scanned tonight (and
        # targets gone from the config), each against its last real scan
        names = (set(last_doc.get("targets") or {}) | set(doc["targets"])) - not_scanned
        before = baseline(previous, names)
        added, removed = now - before, before - now
        summary.update(first_run=False, added=len(added), removed=len(removed), compared_to=previous[-1].name)
        log("aibom", **summary)
        changes("aibom.new", host, added, extra)
        changes("aibom.removed", host, removed, extra)
    else:
        summary.update(first_run=True, added=0, removed=0)
        log("aibom", **summary)
    keep = int(cfg.get("keep_days", 30))
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep)).isoformat()
    for old in state.glob(f"{host}-*.json"):
        if old.stem[len(host) + 1:] < cutoff:
            old.unlink()
    return errors


def main() -> int:
    cfg = json.loads(pathlib.Path(sys.argv[1]).read_text())
    host, state = cfg["host"], pathlib.Path(cfg["state"])
    state.mkdir(parents=True, exist_ok=True)
    targets = [(d["name"], d["path"], "dir", {}) for d in cfg.get("dirs", [])]
    targets += [(f"container:{c}", c, "container", {"key": c}) for c in cfg.get("containers", [])]
    # other hosts' images by digest ({host, name, image, paths}); logged as that host's, scanned_on = this host
    remote = {}
    for r in cfg.get("remote_images", []):
        if r["host"] == host:
            raise SystemExit(f"remote_images entry {r['name']} is for {host} itself: use containers")
        remote.setdefault(r["host"], []).append(
            (f"image:{r['name']}", r["image"], "image", {"key": r["name"], "paths": r.get("paths") or []}))
    pulled = set()
    with tempfile.TemporaryDirectory(prefix="cisco-aibom-") as tmp:
        work = pathlib.Path(tmp)
        errors = run_host(cfg, host, targets, state, work, pulled)
        for rhost, rtargets in sorted(remote.items()):
            errors += run_host(cfg, rhost, rtargets, state, work, pulled, scanned_on=host)
    prune_remote_images(state, {r["image"] for r in cfg.get("remote_images", [])}, pulled)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
