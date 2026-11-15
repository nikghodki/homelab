"""Motor-command sinks: where the governor's output goes. Plain Python (no ROS, no NATS).

- `mock`: records commands (memory, optionally a JSON-lines file). Never touches hardware.
- `http_velocity` (real): POSTs {"linear": vx, "angular": wz} to the car's /velocity endpoint,
  the same call ros2-nav's cmd_vel_bridge makes. The firmware stops by itself when it gets no
  /velocity call for 500 ms.
- `ros_cmd_vel` (real): publishes geometry_msgs/Twist on /cmd_vel; built in node.py because it
  needs rclpy. Only useful with something that turns /cmd_vel into motor calls (cmd_vel_bridge).

A real sink is only built when `real_sink_enabled` is true; otherwise the mock is used and
`make_sink` says so. The default config has it off.
"""

from __future__ import annotations

import collections
import http.client
import json
import threading
import time
from urllib.parse import urlparse

from .core import Velocity

REAL_SINKS = ("http_velocity", "ros_cmd_vel")
SINK_KINDS = ("mock",) + REAL_SINKS


class Sink:
    kind = "base"
    is_real = False

    def send(self, out: Velocity) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class MockSink(Sink):
    kind = "mock"
    is_real = False

    def __init__(self, log_path: str = "", keep: int = 2000, clock=time.time) -> None:
        self.records: collections.deque = collections.deque(maxlen=keep)
        self._clock = clock
        self._file = open(log_path, "a", encoding="utf-8") if log_path else None  # noqa: SIM115

    def send(self, out: Velocity) -> None:
        record = {"t": self._clock(), **out.as_dict()}
        self.records.append(record)
        if self._file:
            self._file.write(json.dumps(record) + "\n")
            self._file.flush()

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None


class HttpVelocitySink(Sink):
    """Sends the latest command from a background thread so a slow car never blocks the governor.

    Only the newest value is sent; anything older is dropped. If the car stops answering, the
    firmware's own 500 ms deadman stops it.
    """

    kind = "http_velocity"
    is_real = True

    def __init__(self, url: str, timeout: float = 0.3, post=None, on_error=None) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("http_velocity sink needs http_url like http://192.168.86.x")
        self._endpoint = url.rstrip("/") + "/velocity"
        # Only http/https to a fixed host: no other URL schemes can be reached.
        self._conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        self._host = parsed.hostname
        self._port = parsed.port
        self._path = parsed.path.rstrip("/") + "/velocity"
        self._timeout = timeout
        self._post = post or self._http_post
        self._on_error = on_error or (lambda exc: None)
        self._pending: Velocity | None = None
        self._cond = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="http-velocity-sink", daemon=True)
        self._thread.start()

    def send(self, out: Velocity) -> None:
        with self._cond:
            self._pending = out
            self._cond.notify()

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._pending is None and not self._closed:
                    self._cond.wait()
                if self._closed and self._pending is None:
                    return
                out, self._pending = self._pending, None
            try:
                self._post(self._endpoint, {"linear": out.vx, "angular": out.wz}, self._timeout)
            except Exception as exc:  # noqa: BLE001 - a failed call must never kill the governor
                self._on_error(exc)

    def _http_post(self, endpoint: str, payload: dict, timeout: float) -> None:
        conn = self._conn_cls(self._host, self._port, timeout=timeout)
        try:
            conn.request("POST", self._path, body=json.dumps(payload), headers={"Content-Type": "application/json"})
            conn.getresponse().read()
        finally:
            conn.close()


def make_sink(sink_cfg: dict, ros_factory=None, on_error=None) -> tuple[Sink, str]:
    """Build the configured sink. Returns (sink, note); note explains a fallback to the mock."""
    kind = sink_cfg.get("kind", "mock")
    if kind not in SINK_KINDS:
        raise ValueError(f"unknown sink kind {kind!r}; one of {', '.join(SINK_KINDS)}")
    mock = MockSink(log_path=sink_cfg.get("mock_log", ""))
    if kind == "mock":
        return mock, ""
    if sink_cfg.get("real_sink_enabled") is not True:
        return mock, f"sink {kind} requested but real_sink_enabled is not true: using the mock sink, motors get nothing"
    mock.close()
    if kind == "http_velocity":
        return HttpVelocitySink(sink_cfg.get("http_url", ""), float(sink_cfg.get("http_timeout", 0.3)), on_error=on_error), ""
    if ros_factory is None:
        raise ValueError("ros_cmd_vel sink needs the ROS node")
    return ros_factory(), ""
