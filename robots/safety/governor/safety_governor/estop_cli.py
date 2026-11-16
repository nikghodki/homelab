"""E-stop from the command line over NATS (no ROS needed).

  safety-estop            latch the e-stop (robot.pi.safety.estop)
  safety-estop status     print the next robot.pi.safety.status message
  safety-reset            clear it (robot.pi.safety.reset, payload RESET), as the operator user

Only the operator user may publish the reset subject (runbooks/robot-safety.md); the wrappers pass
its credentials on stdin (--credentials -) from a root-only file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
from pathlib import Path

import nats

CONFIG = Path.home() / ".config" / "safety-governor"


async def run(action: str, reason: str, config: Path, credentials: str | None) -> int:
    cfg = json.loads(config.read_text())["nats"]
    if credentials == "-":
        creds = json.loads(sys.stdin.read())
    else:
        creds = json.loads(Path(credentials or cfg["credentials_file"]).read_text())
    tls = ssl.create_default_context(cafile=cfg["ca_file"])

    async def error_cb(exc):  # e.g. a permissions violation: this user may not publish the subject
        print(f"NATS error: {exc}", file=sys.stderr)

    nc = await nats.connect(
        servers=[cfg["url"]], user=creds["user"], password=creds["password"], tls=tls,
        name=f"safety-{action}-cli", connect_timeout=5, max_reconnect_attempts=0, error_cb=error_cb,
    )
    try:
        sub = await nc.subscribe(cfg["status_subject"])
        if action == "estop":
            await nc.publish(cfg["estop_subject"], reason.encode())
        elif action == "reset":
            await nc.publish(cfg["reset_subject"], b"RESET")
        await nc.flush()
        want = {"estop": True, "reset": False}.get(action)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5
        st = None
        while loop.time() < deadline:
            try:
                msg = await sub.next_msg(timeout=max(0.1, deadline - loop.time()))
            except Exception:  # noqa: BLE001 - timeout
                break
            st = json.loads(msg.data)
            if want is None or st["estop"]["latched"] is want:
                break
        if st is None:
            print("no status from the governor within 5 s (is safety-governor running?)", file=sys.stderr)
            return 1
        print(json.dumps({k: st[k] for k in ("state", "reason", "detail", "estop", "last_stop", "sink")}, indent=1))
        return 0 if want is None or st["estop"]["latched"] is want else 1
    finally:
        await nc.drain()


def main() -> None:
    p = argparse.ArgumentParser(prog="safety-estop", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("action", nargs="?", default="estop", choices=["estop", "reset", "status"])
    p.add_argument("--reason", default="safety-estop CLI")
    p.add_argument("--config", type=Path, default=CONFIG / "governor.json", help="JSON with a \"nats\" section")
    p.add_argument("--credentials", help="JSON {user, password}; - reads it from stdin (default: the config's)")
    a = p.parse_args()
    sys.exit(asyncio.run(run(a.action, a.reason, a.config, a.credentials)))


if __name__ == "__main__":
    main()
