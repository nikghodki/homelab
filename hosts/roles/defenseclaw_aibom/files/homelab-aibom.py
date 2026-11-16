#!/usr/bin/env python3
"""Nightly AIBOM: save `defenseclaw aibom scan --json` and log what changed since the last run.

The summary line goes to the journal (tag homelab-aibom), which the host collector ships to Loki,
so changes show up in Grafana and can be alerted on. Managed by homelab Ansible (roles/defenseclaw_aibom)."""
import datetime, json, os, pathlib, subprocess, sys

STATE = pathlib.Path(os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local/state")) / "homelab-aibom"
CATEGORIES = ("skills", "plugins", "mcp", "agents", "tools", "model_providers", "rules", "memory", "ide_plugins")


def names(doc: dict) -> dict:
    out = {}
    for cat in CATEGORIES:
        items = doc.get(cat) or []
        out[cat] = sorted({(i.get("name") or i.get("id") or i.get("path") or json.dumps(i, sort_keys=True))
                           if isinstance(i, dict) else str(i) for i in items})
    return out


def main() -> int:
    keep = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    STATE.mkdir(parents=True, exist_ok=True)
    exe = pathlib.Path.home() / ".local/bin/defenseclaw"
    run = subprocess.run([str(exe), "aibom", "scan", "--json"], capture_output=True, text=True, timeout=900)
    if run.returncode != 0:
        print(f"homelab-aibom: scan failed (exit {run.returncode}): {run.stderr.strip()[-300:]}", file=sys.stderr)
        return 1
    doc = json.loads(run.stdout)
    today = STATE / f"aibom-{datetime.date.today().isoformat()}.json"
    # a second run on the same day compares with the last earlier day, not with this morning's file
    previous = [p for p in sorted(STATE.glob("aibom-*.json")) if p != today]
    today.write_text(json.dumps(doc, indent=1))
    now = names(doc)
    summary = {"event": "aibom", "connector": doc.get("connector"), "counts": {k: len(v) for k, v in now.items()}}
    if previous:
        before = names(json.loads(previous[-1].read_text()))
        added = {k: sorted(set(now[k]) - set(before.get(k, []))) for k in CATEGORIES}
        removed = {k: sorted(set(before.get(k, [])) - set(now[k])) for k in CATEGORIES}
        summary["added"] = {k: v for k, v in added.items() if v}
        summary["removed"] = {k: v for k, v in removed.items() if v}
        summary["changed"] = bool(summary["added"] or summary["removed"])
    else:
        summary["changed"] = None  # first run, nothing to compare
    print("homelab-aibom " + json.dumps(summary, sort_keys=True))
    for old in sorted(STATE.glob("aibom-*.json"))[:-keep]:
        old.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
