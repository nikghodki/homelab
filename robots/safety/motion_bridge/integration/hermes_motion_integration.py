"""On-Pi integration test of Hermes' motion path, with the MOCK sink only.

    Hermes' MCP server (the Jetson's patched picoclaw-hardware-mcp.js, built here from the same original and patch)
      --MQTT--> a fake broker on 127.0.0.1, standing in for NATS' MQTT port
      --> a stand-in for the PicoClaw agent (no LLM): it calls picoclaw's real MCP server (as the picoclaw user)
          with the tool and arguments of Hermes' structured request and sends back the result
      --Unix socket--> a test motion bridge --/cmd_vel_in + /safety/heartbeat--> a test governor (mock sink)

Hermes' stop publishes the e-stop on the test topic robot/pi/safety/test/estop; the broker hands it to the test
governor as /safety/estop (what NATS does for robot.pi.safety.estop; the governor's NATS e-stop itself is covered by
run-integration-test). Two fake cars on 127.0.0.1 record every HTTP request, one for each MCP server.

Everything runs in ROS domain 73 (the robot's LiDAR and the deployed governor and bridge are in domain 0), the
governor has NATS off and its config pins sink.kind=mock, and no real broker or credentials are used. Checks: Hermes'
drive forward ends as a clamped Twist at the mock sink; turn passes; strafing is refused; an obstacle blocks;
Nav2 and follow-me are refused without reaching PicoClaw; stop latches the governor's e-stop and calls the car's
/stop; a drive during the e-stop is blocked; no /drive, /turn or /velocity reaches either car. Run on the Pi
(runbooks/robot-safety.md):
  ~/.local/lib/safety-governor/run-hermes-motion-integration-test
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool

from motion_integration import (CODE, CONFIG_DIR, DOMAIN, MOTION_PATHS, RESULTS, FakeCar, Mcp, ScanFeeder, SinkLog,
                                bridge_status, check, moving, wait_until)

REQUEST_TOPIC = "/picoclaw/robot/hermes/request"
RESPONSE_TOPIC = "/picoclaw/robot/hermes/response"
ESTOP_TOPIC = "robot/pi/safety/test/estop"  # NATS robot.pi.safety.test.estop; never the real robot.pi.safety.estop
MOTION_PREFIX = "[hermes-motion v1] "


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---- a minimal MQTT 3.1.1 broker (CONNECT, SUBSCRIBE, PUBLISH QoS 0/1, PING, DISCONNECT), test only ----------

def _remaining_length(n: int) -> bytes:
    out = bytearray()
    while True:
        d, n = n % 128, n // 128
        out.append(d | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _read_packet(rfile):
    first = rfile.read(1)
    if not first:
        return None
    mult, length = 1, 0
    while True:
        d = rfile.read(1)
        if not d:
            return None
        length += (d[0] & 0x7F) * mult
        mult *= 128
        if not d[0] & 0x80:
            break
    return first[0], rfile.read(length) if length else b""


class FakeBroker(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, on_publish) -> None:
        self.on_publish = on_publish
        self.subs: list[tuple[str, object]] = []
        self.published: list[tuple[float, str, bytes]] = []
        self.connects = 0
        broker = self

        class Handler(socketserver.StreamRequestHandler):
            def send(self, data: bytes) -> None:
                with self.lock:
                    self.wfile.write(data)
                    self.wfile.flush()

            def handle(self):
                self.lock = threading.Lock()
                try:
                    while True:
                        pkt = _read_packet(self.rfile)
                        if pkt is None:
                            return
                        kind, body = pkt[0] >> 4, pkt[1]
                        if kind == 1:  # CONNECT
                            broker.connects += 1
                            self.send(b"\x20\x02\x00\x00")
                        elif kind == 3:  # PUBLISH
                            qos = (pkt[0] >> 1) & 3
                            tlen = int.from_bytes(body[:2], "big")
                            topic = body[2:2 + tlen].decode()
                            rest = body[2 + tlen:]
                            if qos:
                                self.send(b"\x40\x02" + rest[:2])
                                rest = rest[2:]
                            broker.published.append((time.time(), topic, rest))
                            threading.Thread(target=broker.on_publish, args=(topic, rest), daemon=True).start()
                        elif kind == 8:  # SUBSCRIBE
                            pid, i, granted = body[:2], 2, b""
                            while i < len(body):
                                tlen = int.from_bytes(body[i:i + 2], "big")
                                broker.subs.append((body[i + 2:i + 2 + tlen].decode(), self))
                                i += 2 + tlen + 1
                                granted += b"\x00"
                            self.send(b"\x90" + _remaining_length(2 + len(granted)) + pid + granted)
                        elif kind == 10:  # UNSUBSCRIBE
                            self.send(b"\xb0\x02" + body[:2])
                        elif kind == 12:  # PINGREQ
                            self.send(b"\xd0\x00")
                        elif kind == 14:  # DISCONNECT
                            return
                except (ConnectionError, OSError):
                    return
                finally:
                    broker.subs = [(t, h) for t, h in broker.subs if h is not self]

        super().__init__(("127.0.0.1", 0), Handler)

    def deliver(self, topic: str, payload: bytes) -> None:
        t = topic.encode()
        pkt_body = len(t).to_bytes(2, "big") + t + payload
        pkt = b"\x30" + _remaining_length(len(pkt_body)) + pkt_body
        for sub_topic, handler in list(self.subs):
            if sub_topic == topic:
                try:
                    handler.send(pkt)
                except OSError:
                    pass

    @property
    def url(self) -> str:
        return f"mqtt://127.0.0.1:{self.server_address[1]}"


class PicoclawStandIn:
    """Plays the PicoClaw agent without its LLM: runs Hermes' structured request with picoclaw's real MCP server."""

    def __init__(self, mcp: Mcp, broker: FakeBroker, estop_pub) -> None:
        self.mcp, self.broker, self.estop_pub = mcp, broker, estop_pub
        self.calls: list[tuple[str, dict]] = []
        self.estops: list[bytes] = []
        self.lock = threading.Lock()

    def on_publish(self, topic: str, payload: bytes) -> None:
        if topic == ESTOP_TOPIC:
            self.estops.append(payload)
            self.estop_pub.publish(Bool(data=True))  # what NATS + the governor's NATS e-stop do
            return
        if topic != REQUEST_TOPIC:
            return
        text = json.loads(payload)["text"]
        first = text.split("\n", 1)[0]
        if not first.startswith(MOTION_PREFIX):
            reply = "test stand-in: free-text requests need the real PicoClaw agent"
        else:
            req = json.loads(first[len(MOTION_PREFIX):])
            with self.lock:
                self.calls.append((req["tool"], req["arguments"]))
                err, out, _, _ = self.mcp.tool(req["tool"], req["arguments"])
            reply = json.dumps({"ok": False, "error": out} if err else {"ok": True, "result": out})
        self.broker.deliver(RESPONSE_TOPIC, json.dumps({"text": reply}).encode())


def build_hermes_copy(dest: Path) -> Path:
    src = Path(os.environ["HERMES_IT_SRC_DIR"])
    dest.mkdir()
    for name in ("picoclaw-hardware-mcp.js", "mcp-common.js", "package.json"):
        shutil.copy(src / name, dest / name)
    (dest / "node_modules").symlink_to(src / "node_modules")
    server = dest / "picoclaw-hardware-mcp.js"
    original = sha256(server) == os.environ["HERMES_IT_ORIGINAL_SHA256"]
    subprocess.run(["patch", "-s", str(server), os.environ["HERMES_IT_PATCH"]], check=True)
    check("Hermes' copy built from the reviewed original + the Jetson's patch (same sha256 as deployed)",
          original and sha256(server) == os.environ["HERMES_IT_PATCHED_SHA256"], sha256(server)[:16])
    return server


def main() -> int:
    if os.environ.get("ROS_DOMAIN_ID") != DOMAIN:
        print(f"refusing to run: set ROS_DOMAIN_ID={DOMAIN} (the wrapper does) so nothing reaches domain 0")
        return 2
    mcp_user = os.environ["MOTION_IT_MCP_USER"]
    deployed = json.loads((CONFIG_DIR / "governor.json").read_text())
    bridge_cfg = json.loads((CONFIG_DIR / "motion-bridge.json").read_text())
    lim = deployed["limits"]
    tmp = Path(tempfile.mkdtemp(prefix="hermes-motion-it-"))
    tmp.chmod(0o711)  # picoclaw's MCP server runs as another user and must reach the test socket
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
    (tmp / "bridge.json").write_text(json.dumps({**bridge_cfg, "socket": sock_path, "socket_mode": 0o666}))
    hermes_server = build_hermes_copy(tmp / "hermes-mcp")

    env = {**os.environ, "PYTHONPATH": str(CODE), "PYTHONUNBUFFERED": "1"}
    procs = [
        subprocess.Popen([sys.executable, "-m", "safety_governor.node", "--config", str(tmp / "governor.json"),
                          "--log-ident", "safety-governor-test"], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True),
        subprocess.Popen([sys.executable, "-m", "motion_bridge.node", "--config", str(tmp / "bridge.json"),
                          "--log-ident", "robot-motion-bridge-test"], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True),
    ]
    pico_car, hermes_car = FakeCar(), FakeCar()
    for car in (pico_car, hermes_car):
        threading.Thread(target=car.serve_forever, daemon=True).start()
    rclpy.init()
    feeder = ScanFeeder()
    estop_pub = feeder.create_publisher(Bool, deployed.get("ros", {}).get("estop_topic", "/safety/estop"),
                                        QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
    executor = SingleThreadedExecutor()
    executor.add_node(feeder)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    sink = SinkLog(sink_path)
    pico = hermes = broker = None
    try:
        ok = wait_until(lambda: os.path.exists(sock_path) and sink.records(), 25)
        check("test governor (mock sink) and test bridge start", ok)
        if not ok:
            return 1
        ok = wait_until(lambda: bridge_status(sock_path).get("governor") is not None, 10)
        check("bridge sees the governor's /safety/status", ok)

        pico = Mcp(["sudo", "-n", "-u", mcp_user, "--", "env",
                    f"PICOCLAW_MOTION_SOCKET={sock_path}", f"ROBOCLAW_API={pico_car.url}",
                    "VISION_PI_API=http://127.0.0.1:9", "MQTT_CREDS_FILE=/nonexistent", "MQTT_BROKER=mqtt://127.0.0.1:9",
                    os.environ["MOTION_IT_MCP_NODE"], os.environ["MOTION_IT_MCP_SERVER"]])
        stand_in = None
        broker = FakeBroker(lambda topic, payload: stand_in.on_publish(topic, payload))
        stand_in = PicoclawStandIn(pico, broker, estop_pub)
        threading.Thread(target=broker.serve_forever, daemon=True).start()

        hermes = Mcp(["env", "-i", f"PATH={os.environ.get('PATH', '/usr/bin:/bin')}", f"HOME={tmp}",
                      f"ROBOCLAW_API={hermes_car.url}", "VISION_PI_API=http://127.0.0.1:9", "ROS2_NAV_DIR=/nonexistent",
                      f"MQTT_BROKER={broker.url}", "MQTT_CREDS_FILE=/nonexistent", "MQTT_PASSWORD=test-only",
                      "MQTT_CA_CERT=/nonexistent", f"PICOCLAW_ESTOP_TOPIC={ESTOP_TOPIC}",
                      os.environ["HERMES_IT_NODE"], str(hermes_server)])
        names = {t["name"] for t in hermes.call("tools/list", {})["tools"]}
        err, text, _, _ = hermes.tool("check_picoclaw_agent_connection")
        check("Hermes' MCP server lists its tools and is connected to the (fake) broker",
              {"drive", "turn", "stop", "send_to_picoclaw_agent"} <= names and '"connected": true' in text,
              f"{len(names)} tools; {text[:80]}")

        # 1. Hermes drive forward at full speed -> PicoClaw -> governor clamps to the cap
        err, text, t0, t1 = hermes.tool("drive", {"direction": "forward", "speed": 255, "duration_ms": 1500})
        recs = [r for r in sink.records(t0, t1) if moving(r)]
        vx = {round(r["vx"], 4) for r in recs}
        check("Hermes drive forward -> PicoClaw drive -> clamped Twist at the mock sink",
              not err and vx == {lim["max_linear"]} and len(recs) >= 8 and "clamped" in text
              and stand_in.calls[-1] == ("drive", {"direction": "forward", "speed": 255, "duration_ms": 1500}),
              f"sink vx {sorted(vx)} in {len(recs)} records; error={err}; picoclaw got {stand_in.calls[-1:]}")
        time.sleep(0.8)
        recs = sink.records(time.time() - 0.3)
        check("motion ends with the call (zero at the sink)", recs and not any(moving(r) for r in recs))

        # 2. turn
        err, text, t0, t1 = hermes.tool("turn", {"direction": "spin_left", "degrees": 45})
        wz = {round(r["wz"], 4) for r in sink.records(t0, t1) if moving(r)}
        check("Hermes turn -> Twist wz at the sink", not err and wz == {bridge_cfg["turn_rate"]}, f"wz {sorted(wz)}")

        # 3. strafing: PicoClaw's tool refuses, Hermes gets an error
        err, text, t0, t1 = hermes.tool("drive", {"direction": "strafe_left", "duration_ms": 500})
        check("Hermes drive strafe -> refused (tool error), nothing at the sink",
              err and not any(moving(r) for r in sink.records(t0, t1)), text[:120])

        # 4. obstacle ahead
        feeder.near = True
        time.sleep(0.5)
        err, text, t0, t1 = hermes.tool("drive", {"direction": "forward", "speed": 120, "duration_ms": 1000})
        check("Hermes drive forward with an obstacle 0.2 m ahead -> blocked (tool error)",
              err and "obstacle" in text and not any(moving(r) for r in sink.records(t0, t1)), text[:160])
        feeder.near = False
        time.sleep(0.5)

        # 5. tools that would drive around the governor are refused on Hermes' side
        n_calls = len(stand_in.calls)
        refused = []
        for name, args in (("navigate_to", {"x": 1.0, "y": 0.0}), ("explore_frontier", {}), ("follow_start", {})):
            err, text, _, _ = hermes.tool(name, args)
            refused.append(err and "disabled" in text)
        check("Hermes navigate_to / explore_frontier / follow_start -> disabled, nothing sent to PicoClaw",
              all(refused) and len(stand_in.calls) == n_calls, f"{refused}")

        # 6. stop: governor e-stop (test topic -> /safety/estop) and the car's /stop
        err, text, t0, t1 = hermes.tool("stop")
        latched = wait_until(lambda: (bridge_status(sock_path)["governor"] or {}).get("estop", {}).get("latched"), 3)
        stops = [p for _, _, p in hermes_car.requests if p == "/stop"]
        check("Hermes stop -> e-stop published on the e-stop topic, governor latched, car /stop called",
              not err and stand_in.estops and latched and stops and ESTOP_TOPIC in text,
              f"estop msgs={len(stand_in.estops)} latched={latched} car={stops}")

        # 7. a drive during the e-stop is blocked
        err, text, t0, t1 = hermes.tool("drive", {"direction": "forward", "speed": 120, "duration_ms": 800})
        check("Hermes drive during the e-stop -> blocked (tool error), nothing at the sink",
              err and "estop" in text and not any(moving(r) for r in sink.records(t0, t1 + 0.3)), text[:160])

        # 8. neither car got a motion request; Hermes' car only /stop; the sink never exceeded the caps
        motion = [(c, p) for c, car in (("picoclaw", pico_car), ("hermes", hermes_car))
                  for _, _, p in car.requests if p.split("?")[0] in MOTION_PATHS]
        check("no /drive, /turn or /velocity request reached either car", not motion,
              f"picoclaw's car saw {sorted({p for _, _, p in pico_car.requests})}, "
              f"Hermes' car saw {sorted({p for _, _, p in hermes_car.requests})}")
        check("Hermes' MCP server called the car only for /stop", {p for _, _, p in hermes_car.requests} == {"/stop"})
        recs = sink.records()
        worst = max((abs(r["vx"]) for r in recs), default=0), max((abs(r["wz"]) for r in recs), default=0)
        check("no output above the caps", worst[0] <= lim["max_linear"] + 1e-9 and worst[1] <= lim["max_angular"] + 1e-9,
              f"{len(recs)} records, max |vx|={worst[0]} |wz|={worst[1]}")
    finally:
        for m in (hermes, pico):
            if m:
                m.close()
        if broker:
            broker.shutdown()
        for p in procs:
            p.terminate()
        outs = []
        for p in procs:
            try:
                outs.append(p.communicate(timeout=10)[0])
            except subprocess.TimeoutExpired:
                p.kill()
                outs.append(p.communicate()[0])
        for car in (pico_car, hermes_car):
            car.shutdown()
        executor.shutdown()
        spinner.join(timeout=5)
        feeder.destroy_node()
        rclpy.shutdown()
        for name, out in zip(("governor", "bridge"), outs):
            tail = "\n".join((out or "").splitlines()[-5:])
            if tail:
                print(f"{name} output (tail):\n{tail}")
        if hermes and hermes.stderr:
            print("Hermes MCP stderr (tail):\n" + "\n".join(hermes.stderr[-5:]))
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed; sink log {sink_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
