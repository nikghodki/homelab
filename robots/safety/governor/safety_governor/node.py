"""ROS 2 node: the only component meant to emit motor commands (runbooks/robot-safety.md).

In:  /cmd_vel_in (Twist), /scan (LaserScan), /safety/estop (Bool true latches),
     /safety/reset (Bool true clears), /safety/heartbeat (Empty);
     NATS robot.pi.safety.estop (any payload latches), robot.pi.safety.reset (payload RESET),
     robot.pi.cmd.heartbeat.
Out: the sink (mock by default), /safety/status and robot.pi.safety.status (JSON),
     interventions to the journal (identifier safety-governor), metrics on 127.0.0.1.

Run: python -m safety_governor.node --config ~/.config/safety-governor/governor.json
"""

from __future__ import annotations

import argparse
import json
import syslog
import threading
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Empty, String

from .core import ZERO, Config, Governor, Scan, Velocity
from .metrics import MetricsServer
from .sinks import Sink, make_sink

DEFAULT_ROS = {
    "scan_topic": "/scan",
    "cmd_in_topic": "/cmd_vel_in",
    "cmd_out_topic": "/cmd_vel",
    "estop_topic": "/safety/estop",
    "reset_topic": "/safety/reset",
    "heartbeat_topic": "/safety/heartbeat",
    "status_topic": "/safety/status",
}
_PRIORITY = {"info": syslog.LOG_INFO, "warning": syslog.LOG_WARNING, "error": syslog.LOG_ERR}


class RosTwistSink(Sink):
    kind = "ros_cmd_vel"
    is_real = True

    def __init__(self, node: Node, topic: str) -> None:
        self._pub = node.create_publisher(Twist, topic, 10)

    def send(self, out: Velocity) -> None:
        msg = Twist()
        msg.linear.x, msg.linear.y, msg.angular.z = out.vx, out.vy, out.wz
        self._pub.publish(msg)


class SafetyGovernorNode(Node):
    def __init__(self, cfg: dict) -> None:
        super().__init__("safety_governor")
        self._lock = threading.RLock()
        self._mono = time.monotonic
        self.gov = Governor(Config.from_dict(cfg.get("limits", {})))
        ros = {**DEFAULT_ROS, **cfg.get("ros", {})}
        self._ros = ros

        sink_cfg = cfg.get("sink", {"kind": "mock"})
        self.sink, note = make_sink(
            sink_cfg,
            ros_factory=lambda: RosTwistSink(self, ros["cmd_out_topic"]),
            on_error=lambda exc: self._log("warning", f"sink error: {exc}", throttle_key="sink"),
        )
        self._throttle: dict[str, float] = {}
        if note:
            self._log("warning", note)
        self._log(
            "info",
            f"sink {self.sink.kind} (real={self.sink.is_real}); limits {json.dumps(self.gov.cfg.as_dict())}",
        )

        reliable = QoSProfile(depth=10)
        self.create_subscription(LaserScan, ros["scan_topic"], self._on_scan, qos_profile_sensor_data)
        self.create_subscription(Twist, ros["cmd_in_topic"], self._on_cmd, reliable)
        self.create_subscription(Bool, ros["estop_topic"], self._on_estop_msg, reliable)
        self.create_subscription(Bool, ros["reset_topic"], self._on_reset_msg, reliable)
        self.create_subscription(Empty, ros["heartbeat_topic"], lambda _m: self.heartbeat(), reliable)
        self._status_pub = self.create_publisher(String, ros["status_topic"], reliable)

        self._last_state = None
        self._status_n = 0
        self.create_timer(1.0 / float(cfg.get("control_rate_hz", 10)), self.tick)
        self.create_timer(1.0 / float(cfg.get("status_rate_hz", 2)), self.publish_status)

        port = int(cfg.get("metrics_port", 0))
        self.metrics = MetricsServer(port) if port else None

        self.nats = None
        self._nats_cfg = cfg.get("nats", {})
        if self._nats_cfg.get("enabled"):
            from .nats_bridge import NatsBridge

            self.nats = NatsBridge(self._nats_cfg, self.estop, self.reset, self.heartbeat, self._log)
            self.nats.start()

    # ---- inputs (any thread) --------------------------------------------------------

    def estop(self, source: str) -> None:
        with self._lock:
            self.gov.estop(self._mono(), source)
        self.tick()

    def reset(self, source: str) -> None:
        with self._lock:
            self.gov.reset(self._mono(), source)
        self.tick()

    def heartbeat(self) -> None:
        with self._lock:
            self.gov.heartbeat(self._mono())

    def _on_estop_msg(self, msg: Bool) -> None:
        if msg.data:
            self.estop("ros")
        else:
            self._log("info", "e-stop false ignored: clearing needs /safety/reset true", throttle_key="estop-false")

    def _on_reset_msg(self, msg: Bool) -> None:
        if msg.data:
            self.reset("ros")

    def _on_scan(self, msg: LaserScan) -> None:
        scan = Scan(msg.angle_min, msg.angle_increment, tuple(msg.ranges), msg.range_min, msg.range_max)
        with self._lock:
            self.gov.scan(self._mono(), scan)

    def _on_cmd(self, msg: Twist) -> None:
        with self._lock:
            self.gov.command(self._mono(), Velocity(msg.linear.x, msg.linear.y, msg.angular.z))

    # ---- outputs ----------------------------------------------------------------------

    def tick(self) -> None:
        with self._lock:
            decision = self.gov.step(self._mono())
            events = self.gov.pop_events()
            self.sink.send(decision.out)
            changed = decision.state != self._last_state
            self._last_state = decision.state
        for ev in events:
            level = "info" if ev["kind"] == "reset" else "warning"
            out = f" out={json.dumps(ev['out'])}" if "out" in ev else ""
            self._log(level, f"INTERVENTION kind={ev['kind']} reason={ev['reason']} detail={ev['detail']}{out}")
        if changed:
            self.publish_status(force_nats=True)

    def publish_status(self, force_nats: bool = False) -> None:
        with self._lock:
            status = self.gov.status(self._mono())
        status.update(
            ts=time.time(),
            sink={"kind": self.sink.kind, "real": self.sink.is_real},
            nats_connected=bool(self.nats and self.nats.connected),
        )
        payload = json.dumps(status, separators=(",", ":"))
        self._status_pub.publish(String(data=payload))
        self._status_n += 1
        if self.nats and (force_nats or self._status_n % 2 == 0):
            self.nats.publish(self._nats_cfg["status_subject"], payload.encode())
        if self.metrics:
            self.metrics.update(
                status_ts=status["ts"],
                estop=status["estop"]["latched"],
                state=status["state"],
                scan_age=status["ages_s"]["scan"] if status["ages_s"]["scan"] is not None else 1e9,
                nats=status["nats_connected"],
                real_sink=self.sink.is_real,
                interventions=status["interventions"],
            )

    def _log(self, level: str, text: str, throttle_key: str | None = None) -> None:
        if throttle_key:
            now = time.monotonic()
            if now - self._throttle.get(throttle_key, -1e9) < 10:
                return
            self._throttle[throttle_key] = now
        syslog.syslog(_PRIORITY.get(level, syslog.LOG_INFO), text)

    def shutdown(self) -> None:
        try:
            self.sink.send(ZERO)
        finally:
            self.sink.close()
            if self.nats:
                self.nats.close()
            if self.metrics:
                self.metrics.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Robot safety governor")
    parser.add_argument("--config", required=True)
    parser.add_argument("--log-ident", default="safety-governor", help="journal identifier (SYSLOG_IDENTIFIER)")
    args = parser.parse_args(argv)
    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    syslog.openlog(args.log_ident, syslog.LOG_PID, syslog.LOG_USER)
    rclpy.init()
    node = SafetyGovernorNode(cfg)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
