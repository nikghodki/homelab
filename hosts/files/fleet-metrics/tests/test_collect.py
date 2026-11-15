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


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_read_thermal_skips_zones_without_data(tmp_path):
    _write(tmp_path / "class/thermal/thermal_zone0/type", "cpu-thermal\n")
    _write(tmp_path / "class/thermal/thermal_zone0/temp", "50312\n")
    _write(tmp_path / "class/thermal/thermal_zone1/type", "cv0-thermal\n")   # no temp file: like a Jetson cv zone
    _write(tmp_path / "class/thermal/thermal_zone2/type", "gpu-thermal\n")
    _write(tmp_path / "class/thermal/thermal_zone2/temp", "garbage\n")
    assert collect.read_thermal(str(tmp_path)) == {"cpu-thermal": 50.3}


def test_read_thermal_missing_root(tmp_path):
    assert collect.read_thermal(str(tmp_path / "none")) == {}


def test_read_power_ina3221(tmp_path):
    mon = tmp_path / "class/hwmon/hwmon3"
    _write(mon / "name", "ina3221\n")
    _write(mon / "in1_label", "VDD_IN\n"); _write(mon / "in1_input", "19000\n"); _write(mon / "curr1_input", "380\n")
    _write(mon / "in2_label", "VDD_CPU_GPU_CV\n"); _write(mon / "in2_input", "19000\n"); _write(mon / "curr2_input", "100\n")
    _write(mon / "in4_input", "5000\n")   # unlabelled channel: skipped
    _write(tmp_path / "class/hwmon/hwmon0/name", "pwmfan\n")
    assert collect.read_power(str(tmp_path)) == {"VDD_IN": 7.22, "VDD_CPU_GPU_CV": 1.9}


def test_read_power_none_elsewhere(tmp_path):
    _write(tmp_path / "class/hwmon/hwmon0/name", "nvme\n")
    assert collect.read_power(str(tmp_path)) == {}
