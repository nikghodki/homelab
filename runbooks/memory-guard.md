# Memory guard on the Sparks

GB10 has 121 GiB of unified memory shared by CPU and GPU. On 2026-11-15 both
Sparks froze (ping answered, sshd did not) after a benchmark used up memory;
nothing was killed and each needed a power cycle.

Why the usual caps do not help: CUDA allocations on GB10 are not charged to the
process's cgroup and do not appear in its RSS. A container started with
`--memory 2g` allocated 4 GiB of GPU memory without complaint, and a process
holding 4.2 GiB of GPU memory showed 0.6 GiB RSS. Docker limits, the kernel OOM
killer and earlyoom therefore either do nothing or kill the wrong process.
`nvidia-smi --query-compute-apps` does attribute GPU memory per host PID.

`roles/memory_guard` (applied by `playbooks/gpu.yml`) installs:

- `gpu-oom-guard`: when MemAvailable drops below 8 GiB (DGXMM's safety
  margin), sends SIGTERM to the process nvidia-smi says holds the most GPU
  memory; SIGKILL if it is still alive 20 s later with memory still short, or at
  once below 6 GiB; then waits 15 s. Every 30 s it also lowers `oom_score_adj` to
  -900 for k3s-server/agent, containerd, dockerd, tailscaled, kube-vip, Caddy
  and CoreDNS, so neither earlyoom nor the kernel picks them. Command lines in
  its log have key/token/secret/password values removed.
- `earlyoom`, the last resort for CPU-side runaways: SIGTERM at 4 % available
  (4.9 GiB), SIGKILL at 2 %; ignores swap. Not at 8 GiB: it ranks by the
  kernel's `oom_score`, and kubelet gives every k3s pod `oom_score_adj` 999
  (score 1332, above an engine's ~980 even with `--prefer`), so it would restart
  pods instead of freeing GPU memory. It prefers the model engines (`VLLM::EngineCor`,
  `vllm`, `llama-server`, `rpc-server`) and never picks the k3s server or agent
  (etcd), containerd and its shims, dockerd, sshd, systemd/journald, tailscaled,
  kube-vip, Caddy (edge pods and Docker), CoreDNS, the guard or itself
  (`--avoid` subtracts 300 from the score in earlyoom 1.7, so the guard's -900
  is what makes that hold). The lists are in
  `roles/memory_guard/defaults/main.yml` (names as in `/proc/<pid>/comm`).

The order as memory runs out: vmalert `FleetMemoryLow` warns at 12 GiB
MemAvailable, the guard asks the largest GPU user to stop at 8 GiB and kills it
at 6 GiB, earlyoom acts at 4.9 GiB.

DGXMM keeps its own 8 GiB margin plus 4 GiB OS reserve, so models it places
never get near the 8 GiB line; the guard is for things outside DGXMM
(benchmarks, ad-hoc containers) and for estimates that turn out wrong.

Check it: `journalctl -u gpu-oom-guard -u earlyoom --since today`, and the
effective lists with `ps -o args= -C earlyoom`. A dry run that shows which
process earlyoom would pick right now, without killing anything (threshold set
just under total memory, so it "acts" at once):

    T=$(awk '/MemTotal/{print $2}' /proc/meminfo)
    sudo timeout 5 earlyoom --dryrun -r 0 -M $((T-1)),$((T-2)) -s 100,100 \
      --avoid "$(ps -o args= -C earlyoom | sed -n "s/.*--avoid \([^ ]*\).*/\1/p")" \
      --prefer "$(ps -o args= -C earlyoom | sed -n "s/.*--prefer \([^ ]*\).*/\1/p")"

Apply: from `hosts/`, `ansible-playbook playbooks/gpu.yml --limit sparks --check --diff`, then without `--check`.
