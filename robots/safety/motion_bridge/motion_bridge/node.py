"""Motion bridge: a Unix socket for picoclaw's MCP server -> the safety governor's ROS inputs.

Socket (default /run/robot-motion/motion.sock, group robot-motion, 0660): one JSON request per
connection, one JSON line back.
  {"op": "drive", "direction": "forward", "speed": 0-255, "duration_ms": N}
  {"op": "turn", "direction": "spin_left", "degrees": N}
  {"op": "move", "vx": m/s, "wz": rad/s, "duration_ms": N}
  {"op": "halt"}     zero command now, cancels a running move (no latch)
  {"op": "stop"}     halt + latch the governor's e-stop (/safety/estop true); clearing it is safety-reset (human)
  {"op": "status"}   the governor's latest /safety/status
A move publishes geometry_msgs/Twist on /cmd_vel_in at cmd_rate_hz and std_msgs/Empty on
/safety/heartbeat at heartbeat_rate_hz for its duration, then one zero Twist, and answers with what
the governor did (moved, clamped, blocked and why). A new move replaces the running one. The
heartbeat only runs while a move runs: no request, no heartbeat, no motion.

Run: python -m motion_bridge.node --config ~/.config/safety-governor/motion-bridge.json
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import struct
import syslog
import threading
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile
from std_msgs.msg import Bool, Empty, String

from .core import Plan, RequestError, load_config, parse_request, plan, precheck, summarize


def log(level: int, text: str) -> None:
    syslog.syslog(level, text)


class MotionBridge(Node):
    def __init__(self, cfg: dict) -> None:
        super().__init__("motion_bridge")
        self.cfg = cfg
        reliable = QoSProfile(depth=10)  # same as the governor's subscriptions
        self._cmd = self.create_publisher(Twist, cfg["cmd_topic"], reliable)
        self._hb = self.create_publisher(Empty, cfg["heartbeat_topic"], reliable)
        self._estop = self.create_publisher(Bool, cfg["estop_topic"], reliable)
        self.create_subscription(String, cfg["status_topic"], self._on_status, reliable)
        self._status_lock = threading.Lock()
        self._status: dict | None = None
        self._status_t: float | None = None
        self._watchers: list[list] = []
        self._move_lock = threading.Lock()  # one move at a time
        self._cancel = threading.Event()

    # ---- governor status --------------------------------------------------------------

    def _on_status(self, msg: String) -> None:
        try:
            st = json.loads(msg.data)
        except ValueError:
            return
        with self._status_lock:
            self._status, self._status_t = st, time.monotonic()
            for w in self._watchers:
                w.append(st)

    def latest(self) -> tuple[dict | None, float | None]:
        with self._status_lock:
            age = None if self._status_t is None else time.monotonic() - self._status_t
            return self._status, age

    # ---- outputs ----------------------------------------------------------------------

    def _twist(self, vx: float, wz: float) -> None:
        msg = Twist()
        msg.linear.x, msg.angular.z = float(vx), float(wz)
        self._cmd.publish(msg)

    def halt(self) -> None:
        self._cancel.set()
        with self._move_lock:  # wait for a running move to end
            self._cancel.clear()
            self._twist(0.0, 0.0)

    def stop(self) -> dict:
        self._cancel.set()
        if self.cfg["estop_on_stop"]:
            self._estop.publish(Bool(data=True))
        self.halt()
        if self.cfg["estop_on_stop"]:
            self._estop.publish(Bool(data=True))
        time.sleep(0.3)
        st, age = self.latest()
        return {"ok": True, "estop_sent": self.cfg["estop_on_stop"],
                "governor": {"state": st.get("state"), "estop": st.get("estop")} if st else None,
                "status_age_s": None if age is None else round(age, 2)}

    def move(self, p: Plan) -> dict:
        st, age = self.latest()
        refused = precheck(st, age, self.cfg)
        if refused:
            return {"ok": False, "blocked": True, "blocked_reason": refused, "commanded": p.as_dict(),
                    "detail": "nothing was published",
                    "governor": {"state": st.get("state"), "reason": st.get("reason")} if st else None}
        self._cancel.set()  # replace a running move
        with self._move_lock:
            self._cancel.clear()
            seen: list = []
            with self._status_lock:
                self._watchers.append(seen)
            period = 1.0 / self.cfg["cmd_rate_hz"]
            hb_every = max(1, round(self.cfg["cmd_rate_hz"] / self.cfg["heartbeat_rate_hz"]))
            start = time.monotonic()
            n = 0
            cancelled = False
            try:
                while True:
                    now = time.monotonic()
                    if now - start >= p.duration_s:
                        break
                    if self._cancel.is_set():
                        cancelled = True
                        break
                    if n % hb_every == 0:
                        self._hb.publish(Empty())
                    self._twist(p.vx, p.wz)
                    n += 1
                    time.sleep(max(0.0, start + n * period - time.monotonic()))
                self._twist(0.0, 0.0)
                time.sleep(0.15)  # let the governor report the last state
            finally:
                with self._status_lock:
                    self._watchers.remove(seen)
        result = summarize(seen, p)
        result.update(ok=not result["blocked"], cancelled=cancelled, published=n)
        return result

    # ---- requests -----------------------------------------------------------------------

    def handle_request(self, req: dict) -> dict:
        op = req["op"]
        if op == "status":
            st, age = self.latest()
            return {"ok": st is not None, "governor": st, "status_age_s": None if age is None else round(age, 2)}
        if op == "halt":
            self.halt()
            return {"ok": True}
        if op == "stop":
            return self.stop()
        return self.move(plan(req, self.cfg))


def _peer(sock: socket.socket) -> str:
    try:
        pid, uid, gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        return f"uid={uid} pid={pid}"
    except OSError:
        return "uid=?"


def serve(bridge: MotionBridge, path: str, mode: int) -> socketserver.ThreadingUnixStreamServer:
    class Handler(socketserver.StreamRequestHandler):
        timeout = 5

        def handle(self) -> None:
            peer = _peer(self.request)
            req = None
            try:
                line = self.rfile.readline(4097)
                req = parse_request(line.strip())
                self.request.settimeout(None)
                reply = bridge.handle_request(req)
            except RequestError as exc:
                reply = {"ok": False, "error": str(exc)}
            except Exception as exc:  # noqa: BLE001 - answer instead of dropping the connection
                reply = {"ok": False, "error": f"bridge error: {exc}"}
            op = req.get("op", "?") if isinstance(req, dict) else "?"
            if op != "status":
                detail = {k: reply.get(k) for k in ("ok", "blocked", "blocked_reason", "clamped", "max_out", "error")
                          if k in reply}
                log(syslog.LOG_INFO if reply.get("ok") else syslog.LOG_WARNING,
                    f"MOTION op={op} {peer} req={json.dumps(req, separators=(',', ':'))} "
                    f"result={json.dumps(detail, separators=(',', ':'))}")
            try:
                self.wfile.write((json.dumps(reply) + "\n").encode())
            except OSError:
                pass

    if os.path.exists(path):
        os.unlink(path)
    # The socket gets mode (0660: the folder's group, robot-motion, may connect; nobody else) via the umask at bind.
    old_umask = os.umask(0o777 & ~mode)
    try:
        server = socketserver.ThreadingUnixStreamServer(path, Handler)
    finally:
        os.umask(old_umask)
    server.daemon_threads = True
    return server


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Motion bridge: MCP motion tools -> safety governor")
    parser.add_argument("--config", required=True)
    parser.add_argument("--socket", help="override the socket path (integration test)")
    parser.add_argument("--log-ident", default="robot-motion-bridge")
    args = parser.parse_args(argv)
    with open(args.config, encoding="utf-8") as fh:
        cfg = load_config(json.load(fh))
    if args.socket:
        cfg["socket"] = args.socket
    syslog.openlog(args.log_ident, syslog.LOG_PID, syslog.LOG_USER)
    rclpy.init()
    bridge = MotionBridge(cfg)
    executor = SingleThreadedExecutor()
    executor.add_node(bridge)
    server = serve(bridge, cfg["socket"], cfg["socket_mode"])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(syslog.LOG_INFO, f"motion bridge on {cfg['socket']} -> {cfg['cmd_topic']} + {cfg['heartbeat_topic']} "
        f"(domain {os.environ.get('ROS_DOMAIN_ID', '0')}); config {json.dumps(cfg, separators=(',', ':'))}")
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        server.shutdown()
        server.server_close()
        try:
            bridge._twist(0.0, 0.0)
        finally:
            if os.path.exists(cfg["socket"]):
                os.unlink(cfg["socket"])
            bridge.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()


if __name__ == "__main__":
    main()
