#!/usr/bin/env python3
"""Scan every agents/*/card.yaml with Cisco's a2a-scanner (offline analyzers only).

Fails on any HIGH or CRITICAL finding. --self-test checks that the scanner still
flags a known-bad card, so a broken scanner can't pass silently.

Usage: scan-agents.py [--self-test]
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
ANALYZERS = ["yara", "heuristic", "spec"]   # no endpoint analyzer: CI makes no calls to agents
BAD = {"HIGH", "CRITICAL"}


def scan(card_json: Path) -> dict:
    cmd = ["a2a-scanner", "scan-card", str(card_json), "-f", "json"]
    for a in ANALYZERS:
        cmd += ["-a", a]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False).stdout
    start = out.find("{")
    if start < 0:
        raise RuntimeError(f"a2a-scanner gave no JSON for {card_json}")
    return json.loads(out[start:])


def blocking(result: dict) -> list:
    return [f for f in result.get("findings", []) if str(f.get("severity", "")).upper() in BAD]


def main() -> int:
    if "--self-test" in sys.argv:
        bad = blocking(scan(Path(__file__).parent / "fixtures/unsafe-agent-card.json"))
        print(f"self-test: unsafe card has {len(bad)} high/critical finding(s)")
        return 0 if bad else 1
    cards = sorted(REPO.glob("agents/*/card.yaml"))
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for card in cards:
            path = Path(tmp) / f"{card.parent.name}.json"
            path.write_text(json.dumps(yaml.safe_load(card.read_text())))
            result = scan(path)
            bad = blocking(result)
            print(f"{card.relative_to(REPO)}: {result.get('total_findings', 0)} finding(s), {len(bad)} high/critical")
            for f in result.get("findings", []):
                prefix = "::error::" if f in bad else "  "
                print(f"{prefix}{card.relative_to(REPO)}: [{f.get('severity')}] {f.get('threat_name')}: {f.get('summary')}")
            failed += bool(bad)
    if not cards:
        print("no agent cards")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
