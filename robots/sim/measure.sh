#!/usr/bin/env bash
# Run one sim job (a `docker compose run` service of hosts/stacks/sim) and sample it every 2 s:
# GPU utilisation, the job's GPU memory (its processes in nvidia-smi), the container's cgroup memory
# and host MemAvailable. A watchdog stops the job if MemAvailable falls under SIM_MIN_AVAIL_GIB
# (default 8), so the Spark's services keep their memory (plan P2.7; runbooks/simulation.md).
#
#   robots/sim/measure.sh <service> [args passed to the service command...]
#
# MLflow: if the job logged an MLflow run (it prints "mlflow: run <id> in experiment <id>") and the client env file
# (SIM_MLFLOW_ENV, default /etc/homelab/mlflow-client.env) is readable, the measurements are added to that same run:
# metrics measure/*, tags measure.*, and the samples as the artifact measure/samples.csv. runbooks/mlflow.md.
set -euo pipefail

svc="${1:?usage: measure.sh <service> [args...]}"
shift
here="$(cd "$(dirname "$0")" && pwd)"
compose=(docker compose -f "$here/../../hosts/stacks/sim/compose.yaml" --profile jobs)
min_avail_gib="${SIM_MIN_AVAIL_GIB:-8}"
min_avail_kib=$((min_avail_gib * 1024 * 1024))
name="sim-${svc}-$(date +%s)"
log="${SIM_LOG_DIR:-/tmp}/${name}.log"
samples="${SIM_LOG_DIR:-/tmp}/${name}.samples.csv"

"${compose[@]}" run --rm --name "$name" "$svc" "$@" >"$log" 2>&1 &
job=$!
echo "job $name, log $log, samples $samples"
echo "t_s,gpu_util_pct,job_gpu_mib,cgroup_mib,host_avail_gib" >"$samples"

sample() {
  # The container can exit between two commands here; a failed sample is skipped, not fatal.
  local cid=$1 util pids gpu cgdir cg p avail
  util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits | head -1)
  pids="|$(docker top "$cid" -eo pid | tail -n +2 | tr '\n' '|')"
  gpu=$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits |
    awk -F', ' -v p="$pids" 'index(p, "|" $1 "|") {s += $2} END {print s + 0}')
  cgdir="/sys/fs/cgroup/system.slice/docker-${cid}.scope"
  cg=$(($(cat "$cgdir/memory.current") / 1048576))
  p=$(($(cat "$cgdir/memory.peak") / 1048576))
  if [ "$p" -gt "$peak" ]; then peak=$p; fi
  avail=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
  echo "$(($(date +%s) - start)),$util,$gpu,$cg,$(echo "scale=1; $avail / 1048576" | bc)" >>"$samples"
  if [ "$avail" -lt "$min_avail_kib" ]; then
    echo "watchdog: MemAvailable below ${min_avail_gib} GiB, stopping $name" | tee -a "$log"
    docker stop -t 10 "$name" >/dev/null
  fi
}

start=$(date +%s)
peak=0
while kill -0 "$job" 2>/dev/null; do
  sleep 2
  cid=$(docker ps -q --no-trunc --filter "name=^${name}$")
  if [ -n "$cid" ]; then sample "$cid" 2>/dev/null || true; fi
done
rc=0
wait "$job" || rc=$?
echo "exit $rc after $(($(date +%s) - start)) s; container memory.peak ${peak} MiB"
awk -F, 'NR > 1 {u += $2; n++; if ($2 > mu) mu = $2; if ($3 > mg) mg = $3; if (min == "" || $5 < min) min = $5}
  END {if (n) printf "samples %d, GPU util mean %.0f%% max %d%%, job GPU memory peak %d MiB, host MemAvailable min %.1f GiB\n",
    n, u / n, mu, mg, min}' "$samples"

# Add the measurements to the job's own MLflow run (same run, so one place has training and footprint). Python's
# standard library only; the credentials stay in the env file and this process, never on a command line.
run_id=$(grep -aoE 'mlflow: run [0-9a-f]{32} in experiment' "$log" | tail -1 | awk '{print $3}' || true)
mlflow_env="${SIM_MLFLOW_ENV:-/etc/homelab/mlflow-client.env}"
if [ -n "$run_id" ] && [ -r "$mlflow_env" ]; then
  watchdog=false
  if grep -q '^watchdog: MemAvailable below' "$log"; then watchdog=true; fi
  python3 - "$mlflow_env" "$run_id" "$samples" "$peak" "$rc" "$watchdog" "$min_avail_gib" "$name" <<'PYEOF' ||
import base64, csv, json, socket, sys, time, urllib.request

env_file, run_id, samples, cg_peak_mib, rc, watchdog, min_avail_gib, name = sys.argv[1:]
env = {}
for line in open(env_file):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k] = v
uri = env.get("MLFLOW_TRACKING_URI", "").rstrip("/")
if not uri:
    sys.exit(0)
user_pass = f"{env.get('MLFLOW_TRACKING_USERNAME', '')}:{env.get('MLFLOW_TRACKING_PASSWORD', '')}"
auth = base64.b64encode(user_pass.encode()).decode()


def call(method, path, body=None, data=None, ctype="application/json"):
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(uri + path, data=data, method=method,
                                 headers={"Authorization": "Basic " + auth, "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = r.read()
        return json.loads(out) if out else {}


rows = list(csv.DictReader(open(samples)))
util = [float(r["gpu_util_pct"]) for r in rows if r["gpu_util_pct"]]
gpu = [float(r["job_gpu_mib"]) for r in rows if r["job_gpu_mib"]]
avail = [float(r["host_avail_gib"]) for r in rows if r["host_avail_gib"]]
metrics = {"measure/samples": len(rows), "measure/container_mem_peak_mib": float(cg_peak_mib)}
if util:
    metrics |= {"measure/gpu_util_mean_pct": sum(util) / len(util), "measure/gpu_util_max_pct": max(util)}
if gpu:
    metrics["measure/job_gpu_mem_peak_mib"] = max(gpu)
if avail:
    metrics |= {"measure/host_mem_available_min_gib": min(avail), "measure/host_mem_available_start_gib": avail[0]}
if rows:
    metrics["measure/wall_s"] = float(rows[-1]["t_s"])
now = int(time.time() * 1000)
tags = {"measure.host": socket.gethostname(), "measure.job": name, "measure.exit_code": rc,
        "measure.watchdog_stopped": watchdog, "measure.min_avail_gib": min_avail_gib, "measure.interval_s": "2"}
call("POST", "/api/2.0/mlflow/runs/log-batch", {
    "run_id": run_id,
    "metrics": [{"key": k, "value": v, "timestamp": now, "step": 0} for k, v in metrics.items()],
    "tags": [{"key": k, "value": str(v)} for k, v in tags.items()],
})
art = call("GET", f"/api/2.0/mlflow/runs/get?run_id={run_id}")["run"]["info"]["artifact_uri"]
prefix = "mlflow-artifacts:/"
if art.startswith(prefix):
    call("PUT", f"/api/2.0/mlflow-artifacts/artifacts/{art[len(prefix):].strip('/')}/measure/samples.csv",
         data=open(samples, "rb").read(), ctype="text/csv")
print(f"mlflow: measurements added to run {run_id}: "
      + ", ".join(f"{k.split('/', 1)[1]} {v:.1f}" for k, v in metrics.items()))
PYEOF
    echo "mlflow: logging the measurements failed; the job's exit code is unchanged"
fi
exit "$rc"
