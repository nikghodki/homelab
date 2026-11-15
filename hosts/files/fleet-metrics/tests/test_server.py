import json
from fleet_metrics import server


def test_build_metrics_shape(monkeypatch):
    monkeypatch.setattr(server.collect, "read_mem", lambda p: {"mem_pct": 50.0, "mem_used_gb": 4.0, "mem_total_gb": 8.0})
    monkeypatch.setattr(server.collect, "read_cpu", lambda p: 12.0)
    monkeypatch.setattr(server.collect, "read_uptime", lambda p: 999.0)
    monkeypatch.setattr(server.collect, "read_gpu", lambda sysfs_path: {"gpu_pct": 40.0, "gpu_name": "Jetson GPU"})
    m = server.build_metrics(proc_root="/proc", sysfs_path="/x")
    assert m == {"cpu_pct": 12.0, "mem_pct": 50.0, "mem_used_gb": 4.0,
                 "mem_total_gb": 8.0, "gpu_pct": 40.0, "gpu_name": "Jetson GPU", "uptime_s": 999.0}


def test_build_services(monkeypatch):
    monkeypatch.setattr(server.services, "collect_services", lambda units, **kw: [{"name": "x", "kind": "unit", "up": True, "detail": "active"}])
    assert server.build_services(["x"]) == {"services": [{"name": "x", "kind": "unit", "up": True, "detail": "active"}]}


def test_route_dispatch(monkeypatch):
    monkeypatch.setattr(server, "build_metrics", lambda **kw: {"ok": "m"})
    monkeypatch.setattr(server, "build_services", lambda units: {"ok": "s"})
    assert server.route("/metrics", units=[], proc_root="/proc", sysfs_path="/x") == (200, {"ok": "m"})
    assert server.route("/services", units=[], proc_root="/proc", sysfs_path="/x") == (200, {"ok": "s"})
    status, _ = server.route("/nope", units=[], proc_root="/proc", sysfs_path="/x")
    assert status == 404


def test_prometheus_rendering():
    m = {"cpu_pct": 12.5, "mem_pct": 50.0, "mem_used_gb": 4.0, "mem_total_gb": 8.0,
         "gpu_pct": 40.0, "gpu_name": "NVIDIA GB10", "uptime_s": 999.0}
    text = server.render_prometheus(m)
    assert "# TYPE fleet_cpu_percent gauge\nfleet_cpu_percent 12.5\n" in text
    assert "fleet_memory_percent 50.0\n" in text
    assert f"fleet_memory_used_bytes {int(4.0 * server.collect._KB_PER_GB * 1024)}\n" in text
    assert f"fleet_memory_total_bytes {int(8.0 * server.collect._KB_PER_GB * 1024)}\n" in text
    assert 'fleet_gpu_percent{gpu_name="NVIDIA GB10"} 40.0\n' in text
    assert "fleet_uptime_seconds 999.0\n" in text
    assert text.endswith("\n")


def test_prometheus_skips_missing_values_and_escapes_labels():
    m = {"cpu_pct": None, "mem_pct": None, "mem_used_gb": None, "mem_total_gb": None,
         "gpu_pct": 1.0, "gpu_name": 'odd "name"\\x', "uptime_s": None}
    text = server.render_prometheus(m)
    assert "fleet_cpu_percent " not in text and "fleet_memory_used_bytes " not in text
    assert 'fleet_gpu_percent{gpu_name="odd \\"name\\"\\\\x"} 1.0\n' in text


def test_route_prometheus(monkeypatch):
    monkeypatch.setattr(server, "build_metrics", lambda **kw: {"cpu_pct": 1.0, "mem_pct": None, "mem_used_gb": None,
                                                               "mem_total_gb": None, "gpu_pct": None, "gpu_name": None, "uptime_s": None})
    status, body = server.route("/metrics/prometheus", units=[], proc_root="/proc", sysfs_path="/x")
    assert status == 200 and isinstance(body, str) and "fleet_cpu_percent 1.0" in body
