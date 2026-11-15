#!/usr/bin/env python3
"""Run the Cisco AI Defense mcp-scanner (YARA analyzer, offline) over every tools/*/tools.json and fail on HIGH.

Each approved MCP server keeps the output of its `tools/list` call in tools/<server>/tools.json. mcp-scanner always
exits 0, so this reads its JSON report and sets the exit code. A finding listed under `accepted_findings` in
tools/<server>/server.yaml is reported as a warning instead, but only while the tool's sha256 still matches the
reviewed one. Usage: scan-mcp-tools.py [tools_dir]
"""
import importlib.util
import json
import pathlib
import subprocess
import sys

import yaml

FAIL_ON = {"HIGH", "CRITICAL"}
_spec = importlib.util.spec_from_file_location("hashes", pathlib.Path(__file__).with_name("mcp-tool-hashes.py"))
hashes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hashes)


def run_scanner(path: pathlib.Path) -> dict:
    out = subprocess.run(["mcp-scanner", "--analyzers", "yara", "--format", "raw", "static", "--tools", str(path)],
                         capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"scanner failed (exit {out.returncode}): {out.stderr.strip()[-300:]}")
    return json.loads(out.stdout or "{}")


def accepted(server_yaml: pathlib.Path) -> list[dict]:
    if not server_yaml.exists():
        return []
    return (yaml.safe_load(server_yaml.read_text()) or {}).get("accepted_findings") or []


def triage(report: dict, tool_hashes: dict[str, str], accepts: list[dict]) -> tuple[list[str], list[str]]:
    """Split HIGH/CRITICAL findings into (problems, accepted)."""
    problems, waived = [], []
    for result in report.get("scan_results", []):
        tool = result.get("tool_name", "?")
        for analyzer, finding in (result.get("findings") or {}).items():
            severity = str(finding.get("severity", "")).upper()
            if severity not in FAIL_ON:
                continue
            msg = f"{tool}: {severity} from {analyzer}: {finding.get('threat_summary', '')}"
            threats = {str(t).upper() for t in finding.get("threat_names") or []}
            ok = any(a.get("tool") == tool and a.get("analyzer") == analyzer
                     and str(a.get("threat", "")).upper() in threats
                     and a.get("sha256") == tool_hashes.get(tool) for a in accepts)
            (waived if ok else problems).append(msg)
    return problems, waived


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools")
    files = sorted(root.glob("*/tools.json"))
    if not files:
        print(f"no MCP tool definitions under {root}/ yet")
        return 0
    failed = False
    for f in files:
        try:
            problems, waived = triage(run_scanner(f), hashes.current(f), accepted(f.with_name("server.yaml")))
        except RuntimeError as e:
            problems, waived = [str(e)], []
        for w in waived:
            print(f"::warning file={f}::accepted in server.yaml: {w}")
        for p in problems:
            print(f"::error file={f}::{p}")
        print(f"{f}: {'FAIL' if problems else 'ok'} ({len(waived)} accepted)")
        failed |= bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
