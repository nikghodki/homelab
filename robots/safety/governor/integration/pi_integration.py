"""On-Pi integration test for the safety governor, with the MOCK sink only.

It starts a second, throw-away governor (ROS_DOMAIN_ID 73, NATS subjects robot.pi.safety.test.*,
no metrics port) next to the deployed one, feeds it fake /scan, /cmd_vel_in and heartbeats,
sends e-stops over NATS as the picoclaw user and over ROS, checks that neither picoclaw nor ROS can
clear them and that the operator user can, and checks what reaches the mock sink.
Nothing here can reach the motors: the config pins sink.kind=mock and real_sink_enabled=false,
the test refuses anything else, and its domain is not the robot's.

Run on the Pi (runbooks/robot-safety.md):
  ~/.local/lib/safety-governor/run-integration-test
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import nats
import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Empty

HERE = Path(__file__).resolve().parent
CODE = HERE.parent  # contains the safety_governor package
CONFIG_DIR = Path.home() / ".config" / "safety-governor"
OPERATOR_CREDENTIALS = "/etc/safety-operator/nats-operator.json"  # root only (role safety_governor)
DOMAIN = "73"
SUBJ = {
    "estop_subject": "robot.pi.safety.test.estop",
    "reset_subject": "robot.pi.safety.test.reset",
    "status_subject": "robot.pi.safety.test.status",
    "heartbeat_subject": "robot.pi.cmd.test.heartbeat",
}
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


class Feeder(Node):
    """Publishes fake inputs at fixed rates; the test changes what it publishes."""

    def __init__(self) -> None:
        super().__init__("safety_governor_test_feeder")
        self.scan_pub = self.create_publisher(LaserScan, "/scan", 10)
        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel_in", 10)
        self.hb_pub = self.create_publisher(Empty, "/safety/heartbeat", 10)
        self.estop_pub = self.create_publisher(Bool, "/safety/estop", 10)
        self.reset_pub = self.create_publisher(Bool, "/safety/reset", 10)
        self.scan_on = True
        self.near = False
        self.hb_on = False
        self.cmd = None  # (vx, wz) or None = not publishing
        self.create_timer(0.1, self._scan)
        self.create_timer(0.1, self._cmd)
        self.create_timer(0.2, self._hb)

    def _scan(self):
        if not self.scan_on:
            return
        n = 360
        msg = LaserScan()
        msg.header.frame_id = "laser_frame"
        msg.angle_min, msg.angle_max = 0.0, 2 * math.pi * (n - 1) / n
        msg.angle_increment = 2 * math.pi / n
        msg.range_min, msg.range_max = 0.05, 20.0
        ranges = [3.0] * n
        if self.near:  # obstacle 0.2 m dead ahead, +-10 deg
            for i in list(range(0, 11)) + list(range(n - 10, n)):
                ranges[i] = 0.2
        msg.ranges = ranges
        self.scan_pub.publish(msg)

    def _cmd(self):
        if self.cmd is None:
            return
        msg = Twist()
        msg.linear.x, msg.angular.z = self.cmd
        self.cmd_pub.publish(msg)

    def _hb(self):
        if self.hb_on:
            self.hb_pub.publish(Empty())


class SinkLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self, since: float) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            rec = json.loads(line)
            if rec["t"] >= since:
                out.append(rec)
        return out

    def wait_for(self, pred, timeout: float, since: float | None = None) -> tuple[bool, float, dict | None]:
        """Wait until the latest sink record satisfies pred. Returns (ok, seconds, record)."""
        start = time.time() if since is None else since
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            recs = self.records(start)
            if recs:
                last = recs[-1]
                if pred(last):
                    return True, last["t"] - start, last
            time.sleep(0.05)
        return False, timeout, last


def is_zero(r):
    return r["vx"] == 0.0 and r["vy"] == 0.0 and r["wz"] == 0.0


def moving(vx, wz=0.0):
    return lambda r: abs(r["vx"] - vx) < 1e-6 and abs(r["wz"] - wz) < 1e-6


class Nats:
    def __init__(self, creds: dict | None = None) -> None:
        creds = creds or json.loads((CONFIG_DIR / "nats-credentials.json").read_text())
        cfg = json.loads((CONFIG_DIR / "governor.json").read_text())["nats"]
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.status: list[dict] = []
        self.errors: list[str] = []

        async def connect():
            tls = ssl.create_default_context(cafile=cfg["ca_file"])
            async def on_error(exc):
                self.errors.append(str(exc))

            nc = await nats.connect(servers=[cfg["url"]], user=creds["user"], password=creds["password"], tls=tls,
                                    name=f"safety-governor-integration-test-{creds['user']}", error_cb=on_error)

            async def on_status(msg):
                self.status.append(json.loads(msg.data))

            await nc.subscribe(SUBJ["status_subject"], cb=on_status)
            return nc

        self.nc = self.run(connect())

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=15)

    def pub(self, subject: str, data: bytes) -> None:
        async def go():
            await self.nc.publish(subject, data)
            await self.nc.flush()

        self.run(go())

    def close(self):
        self.run(self.nc.drain())


def main() -> int:
    if os.environ.get("ROS_DOMAIN_ID") != DOMAIN:
        print(f"refusing to run: set ROS_DOMAIN_ID={DOMAIN} (the wrapper does) so fake /scan never reaches domain 0")
        return 2
    deployed = json.loads((CONFIG_DIR / "governor.json").read_text())
    tmp = Path(tempfile.mkdtemp(prefix="sg-it-"))
    sink_path = tmp / "sink.jsonl"
    cfg = {
        "limits": deployed["limits"],
        "nats": {**deployed["nats"], **SUBJ, "enabled": True},
        "sink": {"kind": "mock", "real_sink_enabled": False, "mock_log": str(sink_path)},
        "control_rate_hz": 10,
        "status_rate_hz": 2,
        "metrics_port": 0,
    }
    assert cfg["sink"]["kind"] == "mock" and cfg["sink"]["real_sink_enabled"] is False
    lim = cfg["limits"]
    (tmp / "governor.json").write_text(json.dumps(cfg))

    env = {**os.environ, "PYTHONPATH": str(CODE), "PYTHONUNBUFFERED": "1"}
    gov = subprocess.Popen([sys.executable, "-m", "safety_governor.node", "--config", str(tmp / "governor.json"),
                            "--log-ident", "safety-governor-test"],
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    rclpy.init()
    feeder = Feeder()
    executor = SingleThreadedExecutor()
    executor.add_node(feeder)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    sink = SinkLog(sink_path)
    bus = operator = None
    try:
        bus = Nats()
        operator = Nats(json.loads(subprocess.run(["sudo", "-n", "cat", OPERATOR_CREDENTIALS], capture_output=True,
                                                  text=True, check=True).stdout))
        ok, _, _ = sink.wait_for(lambda r: True, 20)
        check("governor starts and drives the mock sink", ok)
        if not ok:
            return 1

        # 1. Heartbeat required
        feeder.cmd = (0.1, 0.0)
        ok, _, rec = sink.wait_for(is_zero, 2)
        time.sleep(1.0)
        ok = ok and all(is_zero(r) for r in sink.records(time.time() - 0.8))
        check("no heartbeat -> zero", ok, f"last={rec}")
        feeder.hb_on = True
        ok, dt, rec = sink.wait_for(moving(0.1), 3)
        check("heartbeat + clear scan -> command passes", ok, f"after {dt:.2f}s last={rec}")

        # 2. Speed cap and ceiling
        feeder.cmd = (lim["max_linear"] + 0.2, lim["max_angular"] + 0.5)
        ok, _, rec = sink.wait_for(moving(lim["max_linear"], lim["max_angular"]), 2)
        check("speed cap clamps", ok, f"cmd={feeder.cmd} out={rec}")
        feeder.cmd = (lim["ceiling_linear"] + 0.3, 0.0)
        ok, _, rec = sink.wait_for(is_zero, 2)
        check("above ceiling -> zero", ok, f"cmd={feeder.cmd} out={rec}")

        # 3. Obstacle stop and reversing away
        feeder.near = True
        feeder.cmd = (0.1, 0.0)
        ok, _, rec = sink.wait_for(is_zero, 2)
        check("obstacle 0.2 m ahead blocks forward", ok, f"out={rec}")
        feeder.cmd = (-0.1, 0.0)
        ok, _, rec = sink.wait_for(moving(-0.1), 2)
        check("obstacle ahead: reversing allowed", ok, f"out={rec}")
        feeder.cmd = (0.1, 0.5)
        ok, _, rec = sink.wait_for(moving(0.0, 0.5), 2)
        check("obstacle ahead: turn kept, translation dropped", ok, f"out={rec}")
        feeder.near = False
        feeder.cmd = (0.1, 0.0)
        ok, _, rec = sink.wait_for(moving(0.1), 2)
        check("obstacle gone -> forward again", ok, f"out={rec}")

        # 4. E-stop over NATS (picoclaw user), latched until RESET
        t0 = time.time()
        bus.pub(SUBJ["estop_subject"], b"integration test")
        ok, dt, rec = sink.wait_for(is_zero, 2, since=t0)
        check("NATS e-stop -> zero", ok, f"within {dt:.2f}s")
        feeder.estop_pub.publish(Bool(data=False))
        bus.pub(SUBJ["reset_subject"], b"please")
        time.sleep(1.5)
        ok = all(is_zero(r) for r in sink.records(t0 + dt + 0.05))
        check("stays latched (ROS false, wrong reset payload, fresh commands)", ok)
        st = [s for s in bus.status if s.get("estop", {}).get("latched")]
        check("NATS status reports the latch", bool(st), f"state={st[-1]['state'] if st else None}")
        t1 = time.time()
        bus.pub(SUBJ["reset_subject"], b"RESET")  # picoclaw: the server refuses it
        time.sleep(1.5)
        ok = all(is_zero(r) for r in sink.records(t1))
        denied = [e for e in bus.errors if "permissions violation" in e.lower()]
        check("RESET as picoclaw is refused (still latched, permissions violation)", ok and bool(denied),
              denied[-1] if denied else f"errors={bus.errors}")
        t1 = time.time()
        operator.pub(SUBJ["reset_subject"], b"RESET")
        ok, dt, rec = sink.wait_for(moving(0.1), 2, since=t1)
        check("RESET as operator clears it", ok, f"within {dt:.2f}s")

        # 5. E-stop over ROS
        t0 = time.time()
        feeder.estop_pub.publish(Bool(data=True))
        ok, dt, _ = sink.wait_for(is_zero, 2, since=t0)
        check("ROS /safety/estop true -> zero", ok, f"within {dt:.2f}s")
        time.sleep(0.5)
        t1 = time.time()
        feeder.reset_pub.publish(Bool(data=True))
        time.sleep(1.5)
        ok = all(is_zero(r) for r in sink.records(t1))
        check("ROS /safety/reset true is refused (ROS reset off)", ok)
        t1 = time.time()
        operator.pub(SUBJ["reset_subject"], b"RESET")
        ok, dt, _ = sink.wait_for(moving(0.1), 2, since=t1)
        check("RESET as operator clears it", ok, f"within {dt:.2f}s")

        # 6. Heartbeat watchdog (2 s)
        sink.wait_for(moving(0.1), 2)
        t0 = time.time()
        feeder.hb_on = False
        ok, dt, _ = sink.wait_for(is_zero, 4, since=t0)
        timeout = lim["heartbeat_timeout"]
        check("heartbeat stops -> zero after ~2 s", ok and timeout - 0.5 <= dt <= timeout + 0.6, f"after {dt:.2f}s")
        feeder.hb_on = True
        sink.wait_for(moving(0.1), 3)

        # 7. Stale scan (1 s)
        t0 = time.time()
        feeder.scan_on = False
        ok, dt, _ = sink.wait_for(is_zero, 3, since=t0)
        timeout = lim["scan_timeout"]
        check("scan stops -> zero after ~1 s", ok and timeout - 0.4 <= dt <= timeout + 0.6, f"after {dt:.2f}s")
        feeder.scan_on = True
        ok, _, _ = sink.wait_for(moving(0.1), 2)
        check("scan back -> moves again (not latched)", ok)

        # 8. Command timeout
        t0 = time.time()
        feeder.cmd = None
        ok, dt, _ = sink.wait_for(is_zero, 2, since=t0)
        check("commands stop -> zero", ok, f"after {dt:.2f}s")

        # Never above the caps, whole run
        recs = sink.records(0)
        worst = max((abs(r["vx"]) for r in recs), default=0), max((abs(r["wz"]) for r in recs), default=0)
        check("no output above the caps", worst[0] <= lim["max_linear"] + 1e-9 and worst[1] <= lim["max_angular"] + 1e-9,
              f"{len(recs)} records, max |vx|={worst[0]} |wz|={worst[1]}")
    finally:
        gov.terminate()
        try:
            out, _ = gov.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            gov.kill()
            out, _ = gov.communicate()
        for client in (bus, operator):
            if client:
                client.close()
        executor.shutdown()
        spinner.join(timeout=5)
        feeder.destroy_node()
        rclpy.shutdown()
        tail = "\n".join((out or "").splitlines()[-5:])
        if tail:
            print("governor output (tail):\n" + tail)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed; sink log {sink_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
