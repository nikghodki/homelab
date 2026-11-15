"""Dependency-free host resource collection from /proc. Every reader returns
None for anything it cannot read -- never a fabricated number."""
import os
import subprocess
import time

_KB_PER_GB = 1024 * 1024


def read_mem(proc_root: str = "/proc") -> dict:
    try:
        info = {}
        with open(os.path.join(proc_root, "meminfo")) as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key.strip()] = float(rest.strip().split()[0])  # kB
        total = info.get("MemTotal", 0.0)
        avail = info.get("MemAvailable", 0.0)
        if total <= 0:
            return {"mem_pct": None, "mem_used_gb": None, "mem_total_gb": None}
        used = total - avail
        return {
            "mem_pct": round(used / total * 100, 1),
            "mem_used_gb": round(used / _KB_PER_GB, 2),
            "mem_total_gb": round(total / _KB_PER_GB, 2),
        }
    except (OSError, ValueError, IndexError):
        return {"mem_pct": None, "mem_used_gb": None, "mem_total_gb": None}


def read_uptime(proc_root: str = "/proc") -> float | None:
    try:
        with open(os.path.join(proc_root, "uptime")) as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _cpu_sample(proc_root: str) -> tuple[float, float]:
    with open(os.path.join(proc_root, "stat")) as f:
        parts = f.readline().split()[1:]  # drop "cpu"
    vals = [float(x) for x in parts]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0.0)  # idle + iowait
    total = sum(vals)
    busy = total - idle
    return busy, total


def read_cpu(proc_root: str = "/proc", interval: float = 0.1) -> float | None:
    try:
        b1, t1 = _cpu_sample(proc_root)
        time.sleep(interval)
        b2, t2 = _cpu_sample(proc_root)
        dt = t2 - t1
        if dt <= 0:
            return None
        return round((b2 - b1) / dt * 100, 1)
    except (OSError, ValueError, IndexError):
        return None


def read_gpu(sysfs_path: str = "/sys/devices/platform/gpu.0/load", run=subprocess.run) -> dict:
    # 1. Jetson integrated GPU load
    try:
        with open(sysfs_path) as f:
            raw = float(f.read().strip())
        pct = raw / 10.0 if raw > 100 else raw
        return {"gpu_pct": round(pct, 1), "gpu_name": "Jetson GPU"}
    except (OSError, ValueError):
        pass
    # 2. nvidia-smi - try to get utilization, memory, and temperature
    try:
        r = run(["nvidia-smi", "--query-gpu=utilization.gpu,name,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().splitlines()[0].split(",")
            if len(parts) >= 2:
                util = float(parts[0].strip())
                name = parts[1].strip()
                result = {"gpu_pct": util, "gpu_name": name}
                # Try to parse memory (may be [N/A] on unified-memory boards like DGX GH200)
                if len(parts) >= 4:
                    try:
                        mem_used_mb = float(parts[2].strip())
                        mem_total_mb = float(parts[3].strip())
                        result["gpu_mem_used_gb"] = round(mem_used_mb / 1024, 2)
                        result["gpu_mem_total_gb"] = round(mem_total_mb / 1024, 2)
                    except (ValueError, AttributeError):
                        pass  # Memory not available (unified memory)
                # Try to parse temperature
                if len(parts) >= 5:
                    try:
                        result["gpu_temp_c"] = float(parts[4].strip())
                    except (ValueError, AttributeError):
                        pass
                return result
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return {"gpu_pct": None, "gpu_name": None}
