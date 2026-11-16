"""On-Pi integration test of picoclaw's motion path, with the MOCK sink only.

    picoclaw's real MCP server (run as the picoclaw user)  --Unix socket-->  a test motion bridge
      --/cmd_vel_in + /safety/heartbeat-->  a test governor (mock sink)  ;  fake /scan from this test
    and a fake car on 127.0.0.1 that records every HTTP request the MCP server makes.

Everything runs in ROS domain 73 (the robot's LiDAR and the deployed governor and bridge are in domain 0),
the governor has NATS off, and its config pins sink.kind=mock. Checks: a drive call reaches the mock sink
clamped to the caps; turns and task tools go through the governor; strafing is refused; an obstacle blocks
forward motion (reversing away still works); the heartbeat stops with the move; stop calls the car's /stop
and latches the governor's e-stop; a drive during the e-stop is blocked; and the car never gets /drive,
/turn or /velocity. Run on the Pi (runbooks/robot-safety.md):
  ~/.local/lib/safety-governor/run-motion-integration-test
"""

from __future__ import annotations

import http.server
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import LaserScan

HERE = Path(__file__).resolve().parent
CODE = HERE.parent  # safety_governor and motion_bridge packages
CONFIG_DIR = Path.home() / ".config" / "safety-governor"
DOMAIN = "73"
MOTION_PATHS = ("/drive", "/turn", "/velocity")
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


class ScanFeeder(Node):
    def __init__(self) -> None:
        super().__init__("motion_it_scan")
        self.pub = self.create_publisher(LaserScan, "/scan", 10)
        self.near = False
        self.create_timer(0.1, self._scan)

    def _scan(self):
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
        self.pub.publish(msg)


class FakeCar(http.server.ThreadingHTTPServer):
    """Stands in for the ESP32's HTTP API; records every request."""

    def __init__(self) -> None:
        self.requests: list[tuple[float, str, str]] = []

        car = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                car.requests.append((time.time(), self.command, self.path))
                body = {"ok": True}
                if self.path == "/status":
                    body = {"ok": True, "blocked": False, "recovering": False, "distance_cm": 200}
                elif self.path == "/scan":
                    body = {"readings": [{"angle": a, "distance_cm": 200} for a in range(0, 181, 30)]}
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer

            def log_message(self, *args):
                pass

        super().__init__(("127.0.0.1", 0), Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class SinkLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self, since: float = 0.0, until: float = float("inf")) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            rec = json.loads(line)
            if since <= rec["t"] <= until:
                out.append(rec)
        return out


def moving(r) -> bool:
    return any(abs(r[k]) > 1e-9 for k in ("vx", "vy", "wz"))


class Mcp:
    """Minimal MCP stdio client (JSON-RPC, one message per line)."""

    def __init__(self, cmd: list[str]) -> None:
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True)
        self.stderr: list[str] = []
        threading.Thread(target=self._drain, daemon=True).start()
        self._id = 0
        self.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "motion-integration-test", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _drain(self):
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip())

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params, timeout=40.0):
        self._id += 1
        my_id = self._id
        self._send({"jsonrpc": "2.0", "id": my_id, "method": method, "params": params})
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server exited: " + "\n".join(self.stderr[-10:]))
            msg = json.loads(line)
            if msg.get("id") == my_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg["result"]
        raise TimeoutError(method)

    def tool(self, name, args=None) -> tuple[bool, str, float, float]:
        t0 = time.time()
        res = self.call("tools/call", {"name": name, "arguments": args or {}})
        text = "".join(c.get("text", "") for c in res.get("content", []))
        return bool(res.get("isError")), text, t0, time.time()

    def close(self):
        self.proc.kill()
        self.proc.wait(timeout=5)


def bridge_status(sock_path: str) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(3)
        s.connect(sock_path)
        s.sendall(b'{"op": "status"}\n')
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf)


def wait_until(pred, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.1)
    return False


def main() -> int:
    if os.environ.get("ROS_DOMAIN_ID") != DOMAIN:
        print(f"refusing to run: set ROS_DOMAIN_ID={DOMAIN} (the wrapper does) so nothing reaches domain 0")
        return 2
    mcp_user = os.environ["MOTION_IT_MCP_USER"]
    node_bin = os.environ["MOTION_IT_MCP_NODE"]
    mcp_server = os.environ["MOTION_IT_MCP_SERVER"]
    deployed = json.loads((CONFIG_DIR / "governor.json").read_text())
    bridge_cfg = json.loads((CONFIG_DIR / "motion-bridge.json").read_text())
    lim = deployed["limits"]
    tmp = Path(tempfile.mkdtemp(prefix="motion-it-"))
    tmp.chmod(0o711)  # the MCP server runs as another user and must reach the test socket
    sink_path = tmp / "sink.jsonl"
    sock_path = str(tmp / "motion.sock")
    gov_cfg = {
        "limits": lim,
        "ros": deployed.get("ros", {}),
        "nats": {"enabled": False},
        "sink": {"kind": "mock", "real_sink_enabled": False, "mock_log": str(sink_path)},
        "control_rate_hz": 10,
        "status_rate_hz": 2,
        "metrics_port": 0,
    }
    assert gov_cfg["sink"]["kind"] == "mock" and gov_cfg["sink"]["real_sink_enabled"] is False
    (tmp / "governor.json").write_text(json.dumps(gov_cfg))
    # the MCP server runs as another user: the test socket (in a private temp folder) is open to all
    (tmp / "bridge.json").write_text(json.dumps({**bridge_cfg, "socket": sock_path, "socket_mode": 0o666}))

    env = {**os.environ, "PYTHONPATH": str(CODE), "PYTHONUNBUFFERED": "1"}
    procs = [
        subprocess.Popen([sys.executable, "-m", "safety_governor.node", "--config", str(tmp / "governor.json"),
                          "--log-ident", "safety-governor-test"], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True),
        subprocess.Popen([sys.executable, "-m", "motion_bridge.node", "--config", str(tmp / "bridge.json"),
                          "--log-ident", "robot-motion-bridge-test"], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True),
    ]
    car = FakeCar()
    threading.Thread(target=car.serve_forever, daemon=True).start()
    rclpy.init()
    feeder = ScanFeeder()
    executor = SingleThreadedExecutor()
    executor.add_node(feeder)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    sink = SinkLog(sink_path)
    mcp = None
    try:
        ok = wait_until(lambda: os.path.exists(sock_path) and sink.records(), 25)
        check("test governor (mock sink) and test bridge start", ok)
        if not ok:
            return 1
        ok = wait_until(lambda: bridge_status(sock_path).get("governor") is not None, 10)
        check("bridge sees the governor's /safety/status", ok)

        mcp = Mcp(["sudo", "-n", "-u", mcp_user, "--", "env",
                   f"PICOCLAW_MOTION_SOCKET={sock_path}", f"ROBOCLAW_API={car.url}",
                   "VISION_PI_API=http://127.0.0.1:9", "MQTT_CREDS_FILE=/nonexistent", "MQTT_BROKER=mqtt://127.0.0.1:9",
                   node_bin, mcp_server])
        names = {t["name"] for t in mcp.call("tools/list", {})["tools"]}
        check(f"MCP server runs as {mcp_user} and lists drive/turn/stop", {"drive", "turn", "stop"} <= names,
              f"{len(names)} tools")

        # 1. drive forward at full speed: commanded 0.4 m/s, the governor clamps to the cap
        err, text, t0, t1 = mcp.tool("drive", {"direction": "forward", "speed": 255, "duration_ms": 1500})
        recs = [r for r in sink.records(t0, t1) if moving(r)]
        vx = {round(r["vx"], 4) for r in recs}
        check("MCP drive forward -> clamped Twist reaches the mock sink",
              not err and vx == {lim["max_linear"]} and len(recs) >= 8 and '"clamped": true' in text,
              f"sink vx values {sorted(vx)} in {len(recs)} records; tool error={err}")
        time.sleep(0.8)
        recs = sink.records(time.time() - 0.3)
        check("motion ends with the call (zero at the sink)", recs and not any(moving(r) for r in recs))

        # 2. heartbeat runs only while a move runs
        ok = wait_until(lambda: (bridge_status(sock_path)["governor"] or {}).get("reason") == "heartbeat_timeout",
                        lim["heartbeat_timeout"] + 2)
        check("no move -> no heartbeat (governor: heartbeat_timeout)", ok)

        # 3. turn by degrees, under the cap: passes as commanded
        err, text, t0, t1 = mcp.tool("turn", {"direction": "spin_left", "degrees": 45})
        wz = {round(r["wz"], 4) for r in sink.records(t0, t1) if moving(r)}
        check("MCP turn -> Twist wz reaches the sink", not err and wz == {bridge_cfg["turn_rate"]}, f"wz {sorted(wz)}")

        # 4. strafing is refused before anything is published
        err, text, t0, t1 = mcp.tool("drive", {"direction": "strafe_left", "duration_ms": 500})
        check("MCP drive strafe -> refused, nothing reaches the sink",
              err and not any(moving(r) for r in sink.records(t0, t1)), text[:120])

        # 5. obstacle ahead (fake /scan): forward blocked, reversing away allowed
        feeder.near = True
        time.sleep(0.5)
        err, text, t0, t1 = mcp.tool("drive", {"direction": "forward", "speed": 120, "duration_ms": 1000})
        check("MCP drive forward with an obstacle 0.2 m ahead -> blocked",
              err and "obstacle" in text and not any(moving(r) for r in sink.records(t0, t1)), text[:160])
        err, text, t0, t1 = mcp.tool("drive", {"direction": "backward", "speed": 120, "duration_ms": 800})
        vx = {round(r["vx"], 4) for r in sink.records(t0, t1) if moving(r)}
        check("obstacle ahead: MCP drive backward still moves", not err and vx and max(vx) < 0, f"vx {sorted(vx)}")
        feeder.near = False
        time.sleep(0.5)

        # 6. a task tool (explore) drives through the governor; its end calls the car's /stop
        err, text, t0, t1 = mcp.tool("explore", {"max_seconds": 2, "speed": 160})
        vx = {round(r["vx"], 4) for r in sink.records(t0, t1) if moving(r)}
        check("MCP explore -> forward Twist through the governor", not err and vx == {lim["max_linear"]},
              f"vx {sorted(vx)} error={err} {text[:100] if err else ''}")

        # 7. stop: the car's /stop and the governor's e-stop
        n_before = len(car.requests)
        err, text, t0, t1 = mcp.tool("stop")
        st = bridge_status(sock_path)["governor"] or {}
        stops = [p for _, m, p in car.requests[n_before:] if p == "/stop"]
        check("MCP stop -> governor e-stop latched and car /stop called",
              not err and st.get("estop", {}).get("latched") and stops, f"state={st.get('state')} car={stops}")

        # 8. a drive during the e-stop is blocked
        err, text, t0, t1 = mcp.tool("drive", {"direction": "forward", "speed": 120, "duration_ms": 800})
        check("MCP drive during the e-stop -> blocked, nothing reaches the sink",
              err and "estop" in text and not any(moving(r) for r in sink.records(t0, t1 + 0.3)), text[:160])

        # 9. the car never got a motion request; the sink never exceeded the caps
        motion_calls = [(m, p) for _, m, p in car.requests if p.split("?")[0] in MOTION_PATHS]
        paths = sorted({p for _, _, p in car.requests})
        check("no /drive, /turn or /velocity request reached the car", not motion_calls,
              f"car saw {paths} ({len(car.requests)} requests)")
        recs = sink.records()
        worst = max((abs(r["vx"]) for r in recs), default=0), max((abs(r["wz"]) for r in recs), default=0)
        check("no output above the caps", worst[0] <= lim["max_linear"] + 1e-9 and worst[1] <= lim["max_angular"] + 1e-9,
              f"{len(recs)} records, max |vx|={worst[0]} |wz|={worst[1]}")
    finally:
        if mcp:
            mcp.close()
        for p in procs:
            p.terminate()
        outs = []
        for p in procs:
            try:
                outs.append(p.communicate(timeout=10)[0])
            except subprocess.TimeoutExpired:
                p.kill()
                outs.append(p.communicate()[0])
        car.shutdown()
        executor.shutdown()
        spinner.join(timeout=5)
        feeder.destroy_node()
        rclpy.shutdown()
        for name, out in zip(("governor", "bridge"), outs):
            tail = "\n".join((out or "").splitlines()[-5:])
            if tail:
                print(f"{name} output (tail):\n{tail}")
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed; sink log {sink_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
