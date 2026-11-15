#!/usr/bin/env bash
# Run one sim job (a `docker compose run` service of hosts/stacks/sim) and sample it every 2 s:
# GPU utilisation, the job's GPU memory (its processes in nvidia-smi), the container's cgroup memory
# and host MemAvailable. A watchdog stops the job if MemAvailable falls under SIM_MIN_AVAIL_GIB
# (default 8), so the Spark's services keep their memory (plan P2.7; runbooks/simulation.md).
#
#   robots/sim/measure.sh <service> [args passed to the service command...]
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
exit "$rc"
