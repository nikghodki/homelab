"""measure.sh against stub docker/nvidia-smi. The stub container has no cgroup under /sys/fs/cgroup, so every
cgroup read fails, as when a container exits between `docker ps` and the read: sampling and the memory watchdog
must carry on (an arithmetic error on the failed read used to abandon the sampling loop, watchdog included)."""
import os
import subprocess
from pathlib import Path

MEASURE = Path(__file__).parents[1] / "measure.sh"

DOCKER = """#!/usr/bin/env bash
case "$1" in
  compose) touch "$STUB/alive"; sleep 7; rm -f "$STUB/alive"; exit 7 ;;
  ps) [ -e "$STUB/alive" ] && echo 0123abcd ;;
  top) printf 'PID\\n4242\\n' ;;
  stop) echo "$@" >> "$STUB/stopped" ;;
esac
exit 0
"""
NVIDIA_SMI = """#!/usr/bin/env bash
case "$*" in
  *query-gpu*) echo 42 ;;
  *query-compute-apps*) echo '4242, 512' ;;
esac
"""


def run_measure(tmp_path, min_avail_gib):
    for name, body in (("docker", DOCKER), ("nvidia-smi", NVIDIA_SMI)):
        (tmp_path / name).write_text(body)
        (tmp_path / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "STUB": str(tmp_path),
           "SIM_LOG_DIR": str(tmp_path), "SIM_MIN_AVAIL_GIB": str(min_avail_gib),
           "SIM_MLFLOW_ENV": str(tmp_path / "none.env")}
    return subprocess.run(["bash", str(MEASURE), "stubjob"], env=env, capture_output=True, text=True, timeout=60)


def test_failed_cgroup_read_keeps_sampling(tmp_path):
    r = run_measure(tmp_path, 0)
    assert r.returncode == 7, r.stdout + r.stderr
    rows = next(tmp_path.glob("*.samples.csv")).read_text().splitlines()[1:]
    assert len(rows) >= 2, rows
    t, util, gpu, cgroup, avail = rows[0].split(",")
    assert (util, gpu, cgroup) == ("42", "512", "") and float(avail) > 0


def test_watchdog_fires_although_the_cgroup_read_fails(tmp_path):
    r = run_measure(tmp_path, 10**7)  # no host has 10 PiB available
    assert r.returncode == 7, r.stdout + r.stderr
    assert "watchdog: MemAvailable below" in next(tmp_path.glob("*.log")).read_text()
    assert (tmp_path / "stopped").read_text().startswith("stop -t 10 sim-stubjob-")
