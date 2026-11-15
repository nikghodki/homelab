import os
from fleet_metrics import collect

PROC = os.path.join(os.path.dirname(__file__), "fixtures", "proc")

def test_read_mem():
    m = collect.read_mem(PROC)
    assert m["mem_pct"] == 75.0
    assert round(m["mem_total_gb"], 2) == 7.63
    assert round(m["mem_used_gb"], 2) == 5.72

def test_read_uptime():
    assert collect.read_uptime(PROC) == 123456.78

def test_read_mem_missing_root_returns_nulls():
    m = collect.read_mem("/nonexistent")
    assert m == {"mem_pct": None, "mem_used_gb": None, "mem_total_gb": None}

def test_read_cpu_delta(monkeypatch):
    # two stat reads: busy grows 100 -> 300 out of total grows 1000 -> 1400
    seq = iter([(100.0, 1000.0), (300.0, 1400.0)])
    monkeypatch.setattr(collect, "_cpu_sample", lambda proc_root: next(seq))
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    assert collect.read_cpu(PROC) == 50.0  # 200 busy / 400 total

def test_gpu_jetson_sysfs(tmp_path):
    load = tmp_path / "load"; load.write_text("410\n")  # per-mille -> 41.0
    g = collect.read_gpu(sysfs_path=str(load))
    assert g == {"gpu_pct": 41.0, "gpu_name": "Jetson GPU"}

def test_gpu_nvidia_smi(tmp_path):
    def fake_run(cmd, **kw):
        class R: returncode = 0; stdout = "67, NVIDIA GH200\n"
        return R()
    g = collect.read_gpu(sysfs_path=str(tmp_path / "missing"), run=fake_run)
    assert g == {"gpu_pct": 67.0, "gpu_name": "NVIDIA GH200"}

def test_gpu_none(tmp_path):
    def fake_run(cmd, **kw):
        raise FileNotFoundError()
    g = collect.read_gpu(sysfs_path=str(tmp_path / "missing"), run=fake_run)
    assert g == {"gpu_pct": None, "gpu_name": None}
