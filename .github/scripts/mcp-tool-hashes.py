#!/usr/bin/env python3
"""Pin approved MCP tool definitions: tools/<server>/tools.sha256 holds one sha256 per tool in tools.json.

`check` (CI) fails when a tool was added, removed or changed without the hash file being updated in the same
reviewed PR, so a changed description or schema (tool poisoning, plan P4.3) cannot slip in silently.
`update` rewrites the hash files after a reviewed re-export. Usage: mcp-tool-hashes.py check|update [tools_dir]
"""
import hashlib
import json
import pathlib
import sys


def tool_hash(tool: dict) -> str:
    """sha256 over the whole tool object (name, title, description, inputSchema, annotations ...), canonical JSON."""
    canon = json.dumps(tool, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


def current(tools_json: pathlib.Path) -> dict[str, str]:
    tools = json.loads(tools_json.read_text())["tools"]
    return {t["name"]: tool_hash(t) for t in tools}


def pinned(lock: pathlib.Path) -> dict[str, str]:
    out = {}
    if lock.exists():
        for line in lock.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                digest, name = line.split(maxsplit=1)
                out[name.strip()] = digest
    return out


def diff(tools_json: pathlib.Path) -> list[str]:
    now, pin = current(tools_json), pinned(tools_json.with_name("tools.sha256"))
    problems = [f"{n}: new tool, not in tools.sha256" for n in sorted(now.keys() - pin.keys())]
    problems += [f"{n}: in tools.sha256 but no longer in tools.json" for n in sorted(pin.keys() - now.keys())]
    problems += [f"{n}: definition changed (pinned {pin[n][:12]}, now {now[n][:12]})"
                 for n in sorted(now.keys() & pin.keys()) if now[n] != pin[n]]
    return problems


def write(tools_json: pathlib.Path) -> None:
    lines = ["# sha256 of each approved tool definition in tools.json. Regenerate only after review:",
             "#   .github/scripts/mcp-tool-hashes.py update"]
    lines += [f"{digest}  {name}" for name, digest in sorted(current(tools_json).items())]
    tools_json.with_name("tools.sha256").write_text("\n".join(lines) + "\n")


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "update"):
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    root = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "tools")
    failed = False
    for f in sorted(root.glob("*/tools.json")):
        if sys.argv[1] == "update":
            write(f)
            print(f"{f.with_name('tools.sha256')}: written")
            continue
        problems = diff(f)
        for p in problems:
            print(f"::error file={f}::{p}")
        print(f"{f}: {'CHANGED' if problems else 'ok'}")
        failed |= bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
