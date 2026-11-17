#!/usr/bin/env python3
"""Rescan quarantined Hermes plugins with the LLM judge and restore the ones that pass (runbooks/hermes-profiles.md).

Run on the Jetson as the profile user, in a login shell (DefenseClaw's CLI is in ~/.local/bin):

    plugin_rescan_restore.py scanner-failures      # every plugin whose files are gone and whose latest block is a
                                                   # scanner failure ("the LLM judge did not run", timeouts, 429s)
    plugin_rescan_restore.py named web/firecrawl browser/browserbase   # these (relative to hermes-agent/plugins)

A plugin is copied back from its quarantine copy only if `defenseclaw plugin scan --use-llm` ran the LLM (no
LLM-SCAN-ERROR) and found nothing HIGH or CRITICAL. The script never allow-lists anything; the plugin watcher scans
the restored files again and decides. For plugins inside the Hermes checkout it also checks that the restored files
are the checkout's own (`git status` clean). Results go to stdout and ~/plugin-restore-<timestamp>.log.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}


def candidates(home, base, mode, names):
    db = sqlite3.connect(f"file:{home}/.defenseclaw/audit.db?mode=ro", uri=True)
    rows = db.execute(
        "select original_path, quarantine_path, reason from quarantine_records q where target_type = 'plugin' and "
        "created_at = (select max(created_at) from quarantine_records q2 where q2.original_path = q.original_path)"
    ).fetchall()
    for orig, qpath, reason in rows:
        rel = orig[len(base):] if orig.startswith(base) else orig.replace(home, "~")
        if os.path.exists(orig) or not os.path.isdir(qpath):
            continue
        if mode == "named" and rel not in names:
            continue
        if mode == "scanner-failures" and "scanner failure" not in (reason or ""):
            continue
        yield rel, orig, qpath


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("scanner-failures", "named"):
        sys.exit(__doc__)
    mode, names = sys.argv[1], sys.argv[2:]
    home = os.path.expanduser("~")
    checkout = home + "/.hermes/hermes-agent"
    base = checkout + "/plugins/"
    todo = sorted(candidates(home, base, mode, names))
    log = open(f"{home}/plugin-restore-{time.strftime('%Y%m%d-%H%M%S')}.log", "w")

    def out(*parts):
        line = " ".join(str(p) for p in parts)
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    out(f"{len(todo)} candidates ({mode})")
    for rel, orig, qpath in todo:
        started = time.time()
        scan = subprocess.run(["defenseclaw", "plugin", "scan", qpath, "--use-llm", "--json"],
                              capture_output=True, text=True, timeout=1500)
        took = f"{time.time() - started:.0f}s"
        try:
            findings = json.loads(scan.stdout).get("findings") or []
        except ValueError:
            out("SCAN-FAILED", rel, "rc", scan.returncode, (scan.stderr or "")[-160:].replace("\n", " "))
            continue
        llm_error = [f for f in findings if f.get("rule_id") == "LLM-SCAN-ERROR"]
        high = [f for f in findings if RANK.get(str(f.get("severity", "")).upper(), 0) >= 3]
        top = max((str(f.get("severity", "INFO")).upper() for f in findings), key=lambda s: RANK.get(s, 0),
                  default="none")
        llm = sum(1 for f in findings if str(f.get("rule_id") or "").startswith(("LLM-", "META-LLM-")))
        if llm_error:
            out("KEEP", rel, "LLM did not run:", (llm_error[0].get("title") or "")[:80], took)
            continue
        if high:
            out("KEEP", rel, "max", top, "|", "; ".join(
                f"{f.get('severity')} {f.get('rule_id')} {str(f.get('title', ''))[:60]} @{f.get('location')}"
                for f in high[:6]), took)
            continue
        os.makedirs(os.path.dirname(orig), exist_ok=True)
        shutil.copytree(qpath, orig, symlinks=True, copy_function=shutil.copy2)
        if orig.startswith(base):
            git = subprocess.run(["git", "-C", checkout, "status", "--porcelain", "--", orig],
                                 capture_output=True, text=True)
            same = "git clean" if git.returncode == 0 and not git.stdout.strip() else "git DIFF: " + (
                git.stdout or git.stderr).strip().replace("\n", " ")[:120]
        else:
            same = "outside the checkout (not compared)"
        out("RESTORED", rel, "max", top, f"LLM findings {llm}", same, took)


if __name__ == "__main__":
    main()
