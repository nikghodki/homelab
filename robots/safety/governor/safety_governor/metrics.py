"""A tiny Prometheus endpoint (stdlib only) for the host collector to scrape.

`safety_governor_status_timestamp_seconds` is set when a status message is actually published, so
it goes stale when the governor dies *or* hangs; vmalert alerts on that (runbooks/robot-safety.md).
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATES = ("estop", "fault", "idle", "rejected", "limited", "ok")


def render(snapshot: dict) -> str:
    lines = [
        "# HELP safety_governor_status_timestamp_seconds Unix time of the last published /safety/status.",
        "# TYPE safety_governor_status_timestamp_seconds gauge",
        f"safety_governor_status_timestamp_seconds {snapshot.get('status_ts', 0):.3f}",
        "# HELP safety_governor_estop_latched 1 while the e-stop is latched.",
        "# TYPE safety_governor_estop_latched gauge",
        f"safety_governor_estop_latched {1 if snapshot.get('estop') else 0}",
        "# HELP safety_governor_state 1 for the current state.",
        "# TYPE safety_governor_state gauge",
    ]
    for state in STATES:
        lines.append(f'safety_governor_state{{state="{state}"}} {1 if snapshot.get("state") == state else 0}')
    lines += [
        "# HELP safety_governor_scan_age_seconds Seconds since the last /scan (1e9 = never).",
        "# TYPE safety_governor_scan_age_seconds gauge",
        f"safety_governor_scan_age_seconds {snapshot.get('scan_age', 1e9):.3f}",
        "# HELP safety_governor_nats_connected 1 while connected to NATS.",
        "# TYPE safety_governor_nats_connected gauge",
        f"safety_governor_nats_connected {1 if snapshot.get('nats') else 0}",
        "# HELP safety_governor_real_sink 1 if a real motor sink is active.",
        "# TYPE safety_governor_real_sink gauge",
        f"safety_governor_real_sink {1 if snapshot.get('real_sink') else 0}",
        "# HELP safety_governor_interventions_total Interventions by reason since start.",
        "# TYPE safety_governor_interventions_total counter",
    ]
    for reason, count in sorted(snapshot.get("interventions", {}).items()):
        lines.append(f'safety_governor_interventions_total{{reason="{reason}"}} {count}')
    return "\n".join(lines) + "\n"


class MetricsServer:
    def __init__(self, port: int, host: str = "127.0.0.1") -> None:
        self._lock = threading.Lock()
        self._snapshot: dict = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                if self.path != "/metrics":
                    self.send_error(404)
                    return
                body = render(server.snapshot()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._httpd = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="metrics", daemon=True)
        self._thread.start()

    def update(self, **values) -> None:
        with self._lock:
            self._snapshot.update(values)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._snapshot)

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
