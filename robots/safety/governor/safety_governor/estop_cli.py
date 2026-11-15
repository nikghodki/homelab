"""E-stop from the command line over NATS (no ROS needed), as the picoclaw user.

  safety-estop            latch the e-stop (robot.pi.safety.estop)
  safety-estop reset      clear it (robot.pi.safety.reset, payload RESET)
  safety-estop status     print the next robot.pi.safety.status message
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


async def run(action: str, reason: str) -> int:
    cfg = json.loads((CONFIG / "governor.json").read_text())["nats"]
    creds = json.loads(Path(cfg["credentials_file"]).read_text())
    tls = ssl.create_default_context(cafile=cfg["ca_file"])
    nc = await nats.connect(
        servers=[cfg["url"]], user=creds["user"], password=creds["password"], tls=tls,
        name="safety-estop-cli", connect_timeout=5, max_reconnect_attempts=0,
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
    a = p.parse_args()
    sys.exit(asyncio.run(run(a.action, a.reason)))


if __name__ == "__main__":
    main()
