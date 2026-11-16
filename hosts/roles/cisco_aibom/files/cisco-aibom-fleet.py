#!/usr/bin/env python3
"""Nightly Cisco AIBOM of one host: scan its agent code dirs and AI container images, keep the JSON, log the diff.

Reads a targets file (roles/cisco_aibom/templates/targets.json.j2), runs `cisco-aibom analyze` once per target,
writes <state>/<host>-<date>.json (kept `keep_days` days) and prints journal lines (SyslogIdentifier cisco-aibom)
that the host collector ships to Loki:
  {"event": "aibom", ...}          one summary per run: component counts per type and per target, added/removed
  {"event": "aibom.new", ...}      one per component that was not in the previous run (capped)
  {"event": "aibom.removed", ...}  one per component that is gone (capped)
  {"event": "aibom.skipped", "reason": "skipped: low memory", ...}  an image target not scanned because MemAvailable
                                   was below its threshold (image_min_mem_gib / image_min_mem_gib_by_container)
Secret findings are counted, never named. No LLM is configured, so the BOM is deterministic-only (runbooks/aibom.md).
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


def copy_app_dirs(image: str, dest: pathlib.Path) -> list[str]:
    """Fallback when cisco-aibom's `docker save` discovery fails (Docker's containerd image store drops the
    compressed layers after unpacking): copy the image's working dir and the usual app dirs out of a created,
    never started, container, the way cisco-aibom's own create+cp extraction does."""
    wd = docker("image", "inspect", "-f", "{{.Config.WorkingDir}}", image) or "/"
    wanted = [d for d in dict.fromkeys([wd, "/app", "/opt", "/srv"]) if d != "/"]
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
           "--cache-dir", str(workdir / "cache"), *NO_LLM]
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


def changes(event: str, host: str, items: set) -> None:
    for target, ctype, name, path in sorted(items)[:MAX_LINES]:
        if ctype in HIDDEN_TYPES:
            name = "(secret)"
        log(event, host=host, target=target, type=ctype, name=name, file=path)


def main() -> int:
    cfg = json.loads(pathlib.Path(sys.argv[1]).read_text())
    host, state = cfg["host"], pathlib.Path(cfg["state"])
    state.mkdir(parents=True, exist_ok=True)
    targets = [(d["name"], d["path"], False) for d in cfg.get("dirs", [])]
    targets += [(f"container:{c}", c, True) for c in cfg.get("containers", [])]
    doc = {"host": host, "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "targets": {}}
    errors, skipped = [], []
    min_gib = float(cfg.get("image_min_mem_gib", 0))
    min_gib_by = cfg.get("image_min_mem_gib_by_container") or {}
    with tempfile.TemporaryDirectory(prefix="cisco-aibom-") as tmp:
        work = pathlib.Path(tmp)
        for name, source, is_image in targets:
            entry = {"kind": "image" if is_image else "dir"}
            try:
                if is_image:
                    need = float(min_gib_by.get(source, min_gib))
                    avail = mem_available_gib() if need > 0 else None
                    if avail is not None and avail < need:
                        entry.update(container=source, status="skipped", reason="low memory",
                                     mem_available_gib=round(avail, 1), need_gib=need)
                        skipped.append(name)
                        log("aibom.skipped", host=host, target=name, reason="skipped: low memory",
                            mem_available_gib=round(avail, 1), need_gib=need)
                        doc["targets"][name] = entry
                        continue
                    entry["container"], source = source, image_of(source)
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
                    entry["copied"] = copy_app_dirs(source, app)
                    entry["report"] = scan(cfg["exe"], str(app), False, timeout, work)
                    entry["method"] = "docker-cp-fallback"
                    shutil.rmtree(app, ignore_errors=True)
                entry["status"] = "ok"
            except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError) as e:
                entry["status"], entry["error"] = "error", str(e)[-300:]
                errors.append(f"{name}: {entry['error']}")
            doc["targets"][name] = entry
    doc["finished"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    today = state / f"{host}-{datetime.date.today().isoformat()}.json"
    previous = [p for p in sorted(state.glob(f"{host}-*.json")) if p != today]
    today.write_text(json.dumps(doc, indent=1))
    now = load_components(doc)
    by_type, by_target = counts(now)
    summary = {"host": host, "total": len(now), "counts": by_type, "targets": by_target,
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
        changes("aibom.new", host, added)
        changes("aibom.removed", host, removed)
    else:
        summary.update(first_run=True, added=0, removed=0)
        log("aibom", **summary)
    keep = int(cfg.get("keep_days", 30))
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep)).isoformat()
    for old in state.glob(f"{host}-*.json"):
        if old.stem[len(host) + 1:] < cutoff:
            old.unlink()
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
