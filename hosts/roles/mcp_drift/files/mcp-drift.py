#!/usr/bin/env python3
"""Nightly MCP drift check (plan P4.3): live tools/list against the approved hashes in the homelab repo.

For this account's Hermes config (~/.hermes/config.yaml):

- every configured MCP server has to be in policies/defenseclaw/mcp-servers.yaml with the same launch (URL, or
  full command path and exact argv). One that is not is reported as unapproved and is never started here.
- every approved server that Hermes runs is asked for tools/list the way tools/<name>/tools.json was made
  (export-mcp-tools.py), each tool is hashed as mcp-tool-hashes.py does, and the result is compared with
  tools/<name>/tools.sha256.

Every finding, one line per server and one per run go to the journal as JSON through `logger -t mcp-drift`, so
they reach Loki (Grafana "AI inventory"). Exit 0: no drift; 1: drift or an unapproved server; 2: a check failed.
Managed by homelab Ansible (roles/mcp_drift); the repo files are in --lib.

Usage: mcp-drift [--lib DIR] [--hermes-home DIR] [--no-logger]
"""
import argparse
import importlib.util
import json
import os
import pathlib
import pwd
import re
import signal
import subprocess
import sys
import urllib.parse

import yaml

sys.dont_write_bytecode = True  # the helpers are loaded from --lib; leave no __pycache__ there
STDIO_TIMEOUT_S = 60


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_dotenv(path: pathlib.Path) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                out[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return out


def expand(value: str, env: dict[str, str]) -> str:
    """Hermes-style ${VAR} references, from Hermes' .env first, then the process environment."""
    return re.sub(r"\$\{(\w+)\}", lambda m: env.get(m[1], os.environ.get(m[1], "")), str(value))


def launch_matches(rule: dict, entry: dict) -> bool:
    """The same launch DefenseClaw's registry admits: the exact URL, or the full command path and exact argv."""
    if rule.get("url"):
        return not entry.get("command") and str(entry.get("url", "")).strip() == rule["url"].strip()
    return (not entry.get("url")
            and str(entry.get("command", "")).strip() == str(rule.get("command", "")).strip()
            and [str(a) for a in entry.get("args") or []] == [str(a) for a in rule.get("args_prefix") or []])


def describe(entry: dict) -> str:
    """Where a server runs, without secrets: URL without query, or the command's file name."""
    if entry.get("url"):
        u = urllib.parse.urlsplit(str(entry["url"]))
        return f"{u.scheme}://{u.hostname or ''}{':' + str(u.port) if u.port else ''}{u.path}"
    return os.path.basename(str(entry.get("command", "")))


def compare(live: dict[str, str], pinned: dict[str, str]) -> list[dict]:
    rows = [{"tool": n, "change": "added", "live": live[n][:12]} for n in sorted(live.keys() - pinned.keys())]
    rows += [{"tool": n, "change": "removed", "pinned": pinned[n][:12]} for n in sorted(pinned.keys() - live.keys())]
    rows += [{"tool": n, "change": "changed", "pinned": pinned[n][:12], "live": live[n][:12]}
             for n in sorted(live.keys() & pinned.keys()) if live[n] != pinned[n]]
    return rows


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout(f"no answer within {STDIO_TIMEOUT_S}s")


def list_tools(export, rule: dict, entry: dict, dotenv: dict, probe_env: dict) -> list:
    if rule.get("url"):
        headers = {k.lower(): expand(v, dotenv) for k, v in (entry.get("headers") or {}).items()}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        return export.via_http(rule["url"], token)[1]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(pathlib.Path.home()), **{k: str(v) for k, v in probe_env.items()}}
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(STDIO_TIMEOUT_S)
    try:
        return export.via_stdio([rule["command"], *map(str, rule.get("args_prefix") or [])], env=env)[1]
    finally:
        signal.alarm(0)


def run(lib: pathlib.Path, hermes_home: pathlib.Path, emit) -> int:
    export = load(lib / "export-mcp-tools.py", "export_mcp_tools")
    hashes = load(lib / "mcp-tool-hashes.py", "mcp_tool_hashes")
    approved_doc = yaml.safe_load((lib / "mcp-servers.yaml").read_text())
    approved = {r["name"]: r for r in approved_doc["asset_policy"]["mcp"]["registry"]}
    probes = approved_doc.get("drift_check") or {}
    account = pwd.getpwuid(os.getuid()).pw_name
    config = yaml.safe_load((hermes_home / "config.yaml").read_text()) or {}
    servers = config.get("mcp_servers") or {}
    dotenv = read_dotenv(hermes_home / ".env")
    totals = {"checked": 0, "drift": 0, "unapproved": 0, "errors": 0}

    for name, entry in sorted(servers.items()):
        entry = entry or {}
        if entry.get("enabled") is False:
            continue
        rule = approved.get(name)
        if rule is None or not launch_matches(rule, entry):
            totals["unapproved"] += 1
            emit("warning", event="mcp-drift.server", account=account, server=name, change="unapproved",
                 launch=describe(entry),
                 reason="not in mcp-servers.yaml" if rule is None else "launch differs from mcp-servers.yaml")
            continue
        base = {"event": "mcp-drift", "account": account, "server": name}
        pin_file = lib / "tools" / name / "tools.sha256"
        if not pin_file.exists():
            totals["errors"] += 1
            emit("err", **base, status="error", error=f"no tools/{name}/tools.sha256")
            continue
        totals["checked"] += 1
        try:
            tools = list_tools(export, rule, entry, dotenv, (probes.get(name) or {}).get("env") or {})
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - the export helpers exit on protocol errors
            totals["errors"] += 1
            emit("err", **base, status="error", error=str(exc)[:300] or type(exc).__name__)
            continue
        live = {t["name"]: hashes.tool_hash(t) for t in tools}
        pinned = hashes.pinned(pin_file)
        rows = compare(live, pinned)
        for row in rows:
            emit("warning", event="mcp-drift.tool", account=account, server=name, **row)
        counts = {c: sum(r["change"] == c for r in rows) for c in ("changed", "added", "removed")}
        totals["drift"] += bool(rows)
        emit("warning" if rows else "info", **base, status="drift" if rows else "ok",
             tools=len(live), pinned=len(pinned), **counts)

    status = "error" if totals["errors"] else "drift" if totals["drift"] or totals["unapproved"] else "ok"
    emit("info" if status == "ok" else "warning", event="mcp-drift.run", account=account, status=status,
         configured=len(servers), **totals)
    return {"ok": 0, "drift": 1, "error": 2}[status]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lib", type=pathlib.Path, default=pathlib.Path.home() / ".local/share/homelab-mcp")
    ap.add_argument("--hermes-home", type=pathlib.Path,
                    default=pathlib.Path(os.environ.get("HERMES_HOME", pathlib.Path.home() / ".hermes")))
    ap.add_argument("--no-logger", action="store_true", help="print only, do not write to the journal")
    a = ap.parse_args()

    def emit(priority: str, **fields) -> None:
        line = json.dumps(fields, sort_keys=True)
        print(line, flush=True)
        if not a.no_logger:
            subprocess.run(["logger", "-t", "mcp-drift", "-p", f"user.{priority}", "--", line], check=False)

    return run(a.lib, a.hermes_home, emit)


if __name__ == "__main__":
    sys.exit(main())
