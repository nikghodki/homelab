"""Tiny stdlib HTTP endpoint: GET /metrics and GET /services as JSON, GET /metrics/prometheus as
Prometheus text (scraped by the host OTel collector). No
third-party deps so it runs on the Pi (system python3), Jetson, and DGX
identically. Read-only resource/status data -- no control, no secrets."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fleet_metrics import collect, services

DEFAULT_SYSFS = "/sys/devices/platform/gpu.0/load"


def build_metrics(proc_root: str = "/proc", sysfs_path: str = DEFAULT_SYSFS) -> dict:
    mem = collect.read_mem(proc_root)
    gpu = collect.read_gpu(sysfs_path=sysfs_path)
    return {
        "cpu_pct": collect.read_cpu(proc_root),
        "mem_pct": mem["mem_pct"], "mem_used_gb": mem["mem_used_gb"], "mem_total_gb": mem["mem_total_gb"],
        "gpu_pct": gpu["gpu_pct"], "gpu_name": gpu["gpu_name"],
        "uptime_s": collect.read_uptime(proc_root),
    }


_PROM_GAUGES = [
    ("fleet_cpu_percent", "cpu_pct", "CPU busy, percent", 1),
    ("fleet_memory_percent", "mem_pct", "Memory used (MemTotal - MemAvailable), percent", 1),
    ("fleet_memory_used_bytes", "mem_used_gb", "Memory used, bytes", collect._KB_PER_GB * 1024),
    ("fleet_memory_total_bytes", "mem_total_gb", "Memory total, bytes", collect._KB_PER_GB * 1024),
    ("fleet_uptime_seconds", "uptime_s", "Host uptime, seconds", 1),
]


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_prometheus(m: dict) -> str:
    """The /metrics values as Prometheus text; missing (None) values are left out."""
    out = []
    for name, key, help_text, scale in _PROM_GAUGES:
        if m.get(key) is None:
            continue
        value = m[key] * scale
        out += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge",
                f"{name} {int(value) if scale != 1 else value}"]
    if m.get("gpu_pct") is not None:
        out += ["# HELP fleet_gpu_percent GPU busy, percent", "# TYPE fleet_gpu_percent gauge",
                f'fleet_gpu_percent{{gpu_name="{_label(m.get("gpu_name") or "")}"}} {m["gpu_pct"]}']
    return "\n".join(out) + "\n"


def build_services(units: list[str]) -> dict:
    return {"services": services.collect_services(units)}


def route(path: str, units: list[str], proc_root: str, sysfs_path: str):
    if path == "/metrics":
        return 200, build_metrics(proc_root=proc_root, sysfs_path=sysfs_path)
    if path == "/metrics/prometheus":
        return 200, render_prometheus(build_metrics(proc_root=proc_root, sysfs_path=sysfs_path))
    if path == "/services":
        return 200, build_services(units)
    return 404, {"error": "not found"}


def make_handler(units, proc_root="/proc", sysfs_path=DEFAULT_SYSFS):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = route(self.path, units, proc_root, sysfs_path)
            if isinstance(body, str):
                payload, ctype = body.encode(), "text/plain; version=0.0.4; charset=utf-8"
            else:
                payload, ctype = json.dumps(body).encode(), "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):  # quiet
            pass
    return Handler


def serve(port: int, units: list[str], proc_root="/proc", sysfs_path=DEFAULT_SYSFS):
    httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(units, proc_root, sysfs_path))
    httpd.serve_forever()
