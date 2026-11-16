"""ops-ro: the read-only host commands over SSH (user opsro, forced command, allowlist; runbooks/ops-agent.md)."""
from __future__ import annotations

import asyncio
import re
import shlex

import asyncssh

from ..config import HOSTS, settings

VERBS = {"help", "health", "units", "status", "journal", "kernel", "kernel-prev", "containers", "container-logs",
         "gpu", "net", "k3s", "certs", "defenseclaw"}
_ARG = re.compile(r"^[A-Za-z0-9@._:+-]{1,64}$")
_SINCE = re.compile(r"^-\d{1,4}[smhd]$")


def validate(command: str) -> list[str]:
    """Client-side check (the host re-validates): a known verb and plain arguments, nothing a shell would parse."""
    parts = shlex.split(command)
    if not parts or parts[0] not in VERBS:
        raise ValueError(f"unknown verb; allowed: {', '.join(sorted(VERBS))}")
    ok = lambda a: bool(_ARG.match(a)) and (not a.startswith("-") or bool(_SINCE.match(a)))  # noqa: E731
    if len(parts) > 3 or not all(ok(p) for p in parts[1:]):
        raise ValueError("arguments must be plain names or relative times (e.g. 'journal k3s -2h')")
    return parts


async def run(host: str, command: str, timeout: float = 30.0) -> tuple[bool, str]:
    if host not in HOSTS:
        return False, f"unknown host {host!r}; hosts: {', '.join(HOSTS)}"
    try:
        argv = validate(command)
    except ValueError as e:
        return False, str(e)
    s = settings()
    try:
        async with asyncssh.connect(HOSTS[host]["addr"], username="opsro", client_keys=[s.opsro_key_file],
                                    known_hosts=s.opsro_known_hosts, connect_timeout=10) as c:
            r = await asyncio.wait_for(c.run(" ".join(argv), check=False), timeout)
            out = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
            return r.exit_status == 0, out
    except (OSError, asyncssh.Error, asyncio.TimeoutError) as e:
        return False, f"ssh to {host} failed: {type(e).__name__}: {e}"
