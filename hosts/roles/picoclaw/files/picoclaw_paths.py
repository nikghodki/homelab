#!/usr/bin/env python3
"""Point picoclaw's config.json at its own home (role picoclaw; runbooks/robot-safety.md).

Sets the workspace, the DefenseClaw Lite hook paths and the picoclaw-hardware MCP server (node, script,
motion socket) to the values given as JSON on stdin; leaves everything else as it is (secrets included).
Prints "changed" when it rewrote the file. --check: report only. Fails if any other string still points
into the old home.

  picoclaw_paths.py [--check] < {"config": ..., "home": ..., "old_home": ..., "node": ..., "mcp_server": ...,
                                 "motion_socket": ..., "hook": ..., "hook_lib": ..., "hook_log": ...}
"""
import json
import os
import sys


def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def main() -> int:
    check = "--check" in sys.argv[1:]
    p = json.load(sys.stdin)
    with open(p["config"], encoding="utf-8") as fh:
        text = fh.read()
    cfg = json.loads(text)
    before = json.dumps(cfg, sort_keys=True)

    cfg["agents"]["defaults"]["workspace"] = p["home"] + "/.picoclaw/workspace"
    hook = cfg["hooks"]["processes"]["edge-connector-gate"]
    hook["command"] = ["python3", p["hook"]]
    hook.setdefault("env", {}).update(DCLAW_LIB_PATH=p["hook_lib"], DCLAW_LOG_PATH=p["hook_log"])
    mcp = cfg["tools"]["mcp"]["servers"]["picoclaw-hardware"]
    mcp["command"] = p["node"]
    mcp["args"] = [p["mcp_server"]]
    mcp.setdefault("env", {})["PICOCLAW_MOTION_SOCKET"] = p["motion_socket"]

    stale = [k for k, v in walk(cfg) if p["old_home"] in v]
    if stale:
        print(f"still pointing into {p['old_home']}: {stale}", file=sys.stderr)
        return 1
    if json.dumps(cfg, sort_keys=True) == before:
        print("ok")
        return 0
    print("changed")
    if check:
        return 0
    st = os.stat(p["config"])
    tmp = p["config"] + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, st.st_mode & 0o777)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    os.chown(tmp, st.st_uid, st.st_gid)
    os.replace(tmp, p["config"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
