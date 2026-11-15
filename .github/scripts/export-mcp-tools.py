#!/usr/bin/env python3
"""Print an MCP server's `tools/list` as tools.json (stdlib only, so it runs on any fleet host).

  export-mcp-tools.py --stdio -- <command> [args...]
  export-mcp-tools.py --url http://host/path [--token-env VAR]   # streamable HTTP; token read from $VAR
Review the diff against tools/<server>/tools.json, then run mcp-tool-hashes.py update.
"""
import argparse
import json
import os
import subprocess
import sys
import http.client
import urllib.parse

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "homelab-export", "version": "1"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}


def via_stdio(cmd: list[str]) -> tuple[dict, list]:
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    replies = {}
    try:
        for msg in (INIT, INITIALIZED, LIST):
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            while msg.get("id") and msg["id"] not in replies:
                line = proc.stdout.readline()
                if not line:
                    raise SystemExit("server exited before answering")
                reply = json.loads(line)
                if "id" in reply:
                    replies[reply["id"]] = reply
    finally:
        proc.kill()
    return replies[1]["result"], replies[2]["result"]["tools"]


def via_http(url: str, token: str | None) -> tuple[dict, list]:
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https"):
        raise SystemExit("--url must be http:// or https://")
    conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    path = u.path + (f"?{u.query}" if u.query else "")
    session = None

    def post(msg):
        nonlocal session
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if session:
            headers["Mcp-Session-Id"] = session
        conn = conn_cls(u.netloc, timeout=30)
        try:
            conn.request("POST", path, json.dumps(msg), headers)
            r = conn.getresponse()
            body = r.read().decode()
            if r.status >= 400:
                raise SystemExit(f"HTTP {r.status} from {u.netloc}")
            session = r.getheader("Mcp-Session-Id", session)
        finally:
            conn.close()
        if body.lstrip().startswith(("event:", "data:")):
            body = "\n".join(line[5:].strip() for line in body.splitlines() if line.startswith("data:"))
        return json.loads(body) if body.strip() else None

    init = post(INIT)["result"]
    post(INITIALIZED)
    return init, post(LIST)["result"]["tools"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url")
    ap.add_argument("--token-env")
    ap.add_argument("--stdio", action="store_true")
    ap.add_argument("cmd", nargs="*")
    a = ap.parse_args()
    if a.stdio == bool(a.url) or (a.stdio and not a.cmd):
        ap.error("use exactly one of --stdio -- <command> or --url")
    init, tools = via_stdio(a.cmd) if a.stdio else via_http(a.url, os.environ.get(a.token_env) if a.token_env else None)
    print(json.dumps({"serverInfo": init.get("serverInfo"), "tools": tools}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
