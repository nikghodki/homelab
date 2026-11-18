#!/usr/bin/env python3
"""Weekly DefenseClaw LLM rescan (roles/defenseclaw_rescan).

The watch rescan used to re-scan every skill, plugin and MCP server with the
LLM analyzer every 30 minutes, continuously (the fleet's dominant qwen3.8-27b
caller). It now runs once a week at a fixed time (Sunday 02:00 local,
homelab-rescan.timer): this script runs the same full scan pass standalone
(`skill scan --all`, `plugin scan --all`, `mcp scan --all`, LLM analyzer on,
the key from ~/.defenseclaw/.env via the unit's EnvironmentFile) and prints
one JSON summary line to the journal (tag homelab-rescan), which the host
collector ships to Loki.

Exit codes: 0 clean; 1 findings at/above the policy threshold or per-target
errors (the normal state on a fleet with blocked skills -- the unit carries
SuccessExitStatus=1); 2 hard failure (no CLI, a scan command timed out, or
emitted nothing parseable with a nonzero exit). Managed by homelab Ansible."""
import json
import os
import pathlib
import subprocess
import sys
import time

EXE = pathlib.Path.home() / ".local/bin" / "defenseclaw"
SEVERE = ("CRITICAL", "HIGH")
# A category (all skills, or all plugins, or all MCP servers) that takes longer
# than this is stuck (a hung LLM call, not a big scan): give it 6 h, the same
# budget the unit's TimeoutStartSec allows for the whole job.
CATEGORY_TIMEOUT_S = 6 * 3600

# The same scan pass the gateway's watch rescan runs (confirmed in audit.db's
# scan_results): skills and plugins with the LLM analyzer, and MCP servers --
# without --allow-private, because the watch's own mcp-scanner refuses loopback
# / private URLs by default (the homeassistant MCP records a refusal every pass,
# exit 1), so this job reproduces that scope rather than widening it.
SCAN = (
    ("skills", ["skill", "scan", "--all", "--use-llm"]),
    ("plugins", ["plugin", "scan", "--all", "--use-llm"]),
    ("mcp", ["mcp", "scan", "--all"]),
)


def flatten(doc, category):
    """One entry per scanned target, whatever the category's JSON nesting."""
    if category == "plugins":
        # [{connector, results: [{target, findings, ...}]}]
        return [r for c in doc for r in (c.get("results") or [])]
    # skills and mcp are already flat lists of {target, findings, error?}
    return doc


def summarize(items):
    findings = 0
    severe = 0
    errors = 0
    for item in items:
        fs = item.get("findings") or []
        findings += len(fs)
        severe += sum(1 for f in fs if str(f.get("severity", "")).upper() in SEVERE)
        if item.get("error"):
            errors += 1
    return {"targets": len(items), "findings": findings,
            "severe_findings": severe, "errors": errors}


def run_scan(args):
    """Run one scan category; return (items | None, returncode, error | None, seconds)."""
    start = time.monotonic()
    try:
        proc = subprocess.run([str(EXE), *args, "--json"], capture_output=True,
                              text=True, timeout=CATEGORY_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, 2, f"error: {type(exc).__name__} after {time.monotonic() - start:.0f}s", time.monotonic() - start
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        tail = proc.stderr.strip()[-200:]
        return None, proc.returncode, f"error: non-JSON output (rc={proc.returncode}): {tail}", time.monotonic() - start
    return doc, proc.returncode, None, time.monotonic() - start


def main():
    if not EXE.is_file():
        print(f"homelab-rescan: no defenseclaw CLI at {EXE}", file=sys.stderr)
        return 2
    summary = {"event": "defenseclaw-rescan"}
    exit_code = 0
    for category, args in SCAN:
        doc, rc, err, seconds = run_scan(args)
        if err is not None:
            summary[category] = {"error": err, "duration_s": round(seconds)}
            if rc >= 2:
                exit_code = 2
            else:
                exit_code = max(exit_code, 1)
            continue
        summary[category] = summarize(flatten(doc, category))
        summary[category]["duration_s"] = round(seconds)
        if rc == 1:
            # Findings at/above the policy threshold (a blocked skill) -- a
            # state the watch would have recorded too, not a job failure.
            exit_code = max(exit_code, 1)
    summary["duration_s"] = sum(v.get("duration_s", 0) for v in summary.values() if isinstance(v, dict))
    print("homelab-rescan " + json.dumps(summary, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
