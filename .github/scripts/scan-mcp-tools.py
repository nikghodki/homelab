#!/usr/bin/env python3
"""Run the Cisco AI Defense mcp-scanner (YARA analyzer, offline) over every tools/*/tools.json and fail on HIGH.

Each approved MCP server keeps the output of its `tools/list` call in tools/<server>/tools.json. mcp-scanner always
exits 0, so this reads its JSON report and sets the exit code. Usage: scan-mcp-tools.py [tools_dir]
"""
import json
import pathlib
import subprocess
import sys

FAIL_ON = {"HIGH", "CRITICAL"}


def scan(path: pathlib.Path) -> list[str]:
    out = subprocess.run(["mcp-scanner", "--analyzers", "yara", "--format", "raw", "static", "--tools", str(path)],
                         capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return [f"scanner failed (exit {out.returncode}): {out.stderr.strip()[-300:]}"]
    report = json.loads(out.stdout or "{}")
    problems = []
    for result in report.get("scan_results", []):
        for analyzer, finding in (result.get("findings") or {}).items():
            severity = str(finding.get("severity", "")).upper()
            if severity in FAIL_ON:
                tool = result.get("tool_name", "?")
                problems.append(f"{tool}: {severity} from {analyzer}: {finding.get('threat_summary', '')}")
    return problems


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools")
    files = sorted(root.glob("*/tools.json"))
    if not files:
        print(f"no MCP tool definitions under {root}/ yet")
        return 0
    failed = False
    for f in files:
        problems = scan(f)
        for p in problems:
            print(f"::error file={f}::{p}")
        print(f"{f}: {'FAIL' if problems else 'ok'}")
        failed |= bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
