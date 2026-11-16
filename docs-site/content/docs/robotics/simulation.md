---
title: "Simulation (Isaac Lab and MuJoCo)"
description: "On-demand simulation jobs on dgx-2: images, how to run them, measured throughput and memory, the memory caps, and MLflow logging."
---

Isaac Lab 3.0 and MuJoCo Playground run as on-demand containers on **dgx-2 only** (dgx-1 serves models). Plan P6.2,
P6.4; `hosts/stacks/sim/compose.yaml`; runbooks/simulation.md.

## Jobs

Both services are in the compose profile `jobs`: they never start on their own (`restart: "no"`), are capped at
16 GiB cgroup memory (`mem_limit` and `memswap_limit`), drop all capabilities, `no-new-privileges`, bridge network,
2 GiB shm, all GPUs, and are removed when they exit.

| Service | Image | What |
|---|---|---|
| `isaaclab` | `homelab/isaaclab:3.0.0-kitless-mlflow3.18.0`, built locally from `robots/sim/isaaclab/Dockerfile`: NVIDIA's `nvcr.io/nvidia/isaac-lab:3.0.0-kitless` (NGC, multi-arch, pinned by digest) plus only `mlflow-skinny` 3.18.0 (every existing package held at its version; the build fails if one changes) | Isaac Lab 3.0.0, Newton physics, headless, no Isaac Sim (no EULA, no RTX rendering). Ubuntu 24.04, Python 3.12, PyTorch 2.11 cu130, RSL-RL 5.5.1, skrl 2.1.0. Entrypoint `robots/sim/isaaclab/train_mlflow.py` (mounted read-only, takes the `isaaclab` command's arguments). Logs in volume `sim_isaaclab-logs` |
| `mujoco` | `homelab/mujoco-playground:0.2.0-jax0.9.2-mlflow3.18.0`, built locally from `robots/sim/mujoco` | MuJoCo 3.6 + MJX + Playground 0.2.0, JAX 0.9.2 on CUDA 13, Brax 0.14.2 PPO, warp-lang 1.12.0, mlflow-skinny 3.18.0. `XLA_PYTHON_CLIENT_PREALLOCATE=false`, `XLA_PYTHON_CLIENT_MEM_FRACTION=0.15` |

Both images live only in dgx-2's local Docker (MuJoCo isn't built in CI: about 12 GB of CUDA wheels). Compose builds
only when a tag is missing: bump the tag when a Dockerfile changes.

## Run

```bash
# from dgx-1: copy the two folders (compose builds from ../../../robots/sim/mujoco)
cd ~/homelab && git pull
rsync -aR --delete ./hosts/stacks/sim ./robots/sim nikghodki-dgx-2@192.168.86.36:sim-repo/
ssh nikghodki-dgx-2@192.168.86.36
cd ~/sim-repo && df -h /                                       # keep at least 15% free
docker compose -f hosts/stacks/sim/compose.yaml --profile jobs build isaaclab   # pulls NVIDIA's image (5.3 GB), adds ~0.1 GB
docker compose -f hosts/stacks/sim/compose.yaml --profile jobs build mujoco     # ~6 min, 12.4 GB on disk
robots/sim/measure.sh isaaclab train --rl_library rsl_rl --task Isaac-Cartpole-Direct --max_iterations 1000 physics=newton_mjwarp
robots/sim/measure.sh mujoco                                   # Go1JoystickFlatTerrain, MJX warp, ~26M steps
```

`robots/sim/measure.sh` runs one job and samples every 2 s: GPU utilisation, the job's GPU memory, cgroup memory and
host MemAvailable. Its watchdog **stops the job if MemAvailable drops under `SIM_MIN_AVAIL_GIB` (default 8)**. Logs and
samples go to `/tmp/sim-<service>-<epoch>.{log,samples.csv}`.

## Measured (2026-11-15, dgx-2, a DGXMM engine loaded and idle)

| Run | Envs | Steps | Time | Throughput | GPU util mean/max | Job GPU mem | cgroup peak | MemAvailable min |
|---|---|---|---|---|---|---|---|---|
| Isaac Lab Cartpole-Direct, RSL-RL PPO, 1000 it | 4096 | 65.5 M | 137 s | 487 k steps/s | 17% / 39% | 371 MiB | 3.1 GiB | 25.1 GiB |
| Isaac Lab Velocity-Flat-AnymalD, 200 it | 4096 | 19.7 M | 221 s | 98 k steps/s | 63% / 92% | 1.2 GiB | 3.2 GiB | 24.2 GiB |
| Playground Go1JoystickFlatTerrain, MJX warp | 8192 | 26.2 M | 164 s (20 s JIT) | 183 k overall, 224 k steady | 68% / 96% | 2.5 GiB | 2.5 GiB | 23.1 GiB |
| Playground Go1, MJX jax | 8192 | 13.1 M | 205 s (53 s JIT) | 180 k steady | 35% / 96% | 2.4 GiB | 3.1 GiB | 22.5 GiB |

Learning is real: Cartpole reaches success 1.0; Go1's eval reward goes 0 → 19.6 in 20 M steps.

## Memory

GB10 memory is unified: CUDA allocations are **not** charged to the container's cgroup. So each job is capped twice:
`mem_limit: 16g` on the CPU side, and per framework on the GPU side (JAX 15% ≈ 18 GiB; Isaac Lab via `--num_envs`).
Run one job at a time, only when `free -g` shows room above dgx-2's 15–23 GiB service reserve. Bigger runs need a DGXMM
budget entry first (P6.6).

## MLflow logging

When `/etc/homelab/mlflow-client.env` exists on dgx-2 (written by `playbooks/ml.yml`), both services load it
(`env_file`, `required: false`):

- **MuJoCo** (`train_ppo.py`, experiment `sim-mujoco`): hyperparameters, `eval/*` metrics, steps/s, `final/*`,
  `summary.json`, the policy params (`policy/policy_params.pkl`).
- **Isaac Lab RSL-RL** (`train_mlflow.py`, experiment `sim-isaaclab`, run name `<task>-<iterations>it`): the runner and
  env config as params and JSON artifacts; every iteration's `Train/mean_reward`, episode length, `Perf/total_fps`,
  losses and task metrics; `final/*`, `summary.json` and the final checkpoint. TensorBoard files stay in the volume.
  skrl, rl_games and sb3 runs aren't hooked.
- **`measure.sh`** adds its numbers to the **same run** after the job exits, when the job printed
  `mlflow: run <id> in experiment <id>`: `measure/gpu_util_mean_pct`, `measure/gpu_util_max_pct`,
  `measure/job_gpu_mem_peak_mib`, `measure/container_mem_peak_mib`, `measure/host_mem_available_min_gib`, `measure/wall_s`,
  tags `measure.*` (host, job, exit code, whether the watchdog stopped it) and `measure/samples.csv`.

`-e MLFLOW_TRACKING_URI=` turns logging off for one run. A failed MLflow call disables logging; training continues. A
run stopped by `docker stop` or the watchdog ends `KILLED`. See [MLflow](../services/mlflow.md).

Test runs with measure.sh logging (2026-11-15, about 114 GiB available before each job): Isaac Lab Cartpole 300 it,
19.7 M steps in 60 s, 508 k steps/s median, success rate 1.0, cgroup peak 3.7 GiB; MuJoCo Go1 10 M, 13.1 M steps in
112 s, 202 k steady steps/s, cgroup peak 3.5 GiB, job GPU 2.5 GiB.

## Notes

- Isaac Lab 3.0 has no `--headless` flag (kit-less is headless unless `--viz`), and ships no wheeled-robot task; Anymal-D
  stands in until our own robot task (P6.1, P6.7).
- XLA prints `xtile_compiler.cc` autotune errors on GB10; training continues.
- Isaac Sim (P6.3): `nvcr.io/nvidia/isaac-sim:6.2.0` (arm64, 9.3 GB) and the full Isaac Lab image exist; DGX Spark is
  the only supported aarch64 system. Not pulled or tested.
- Disk: 16.3 GB + 12.4 GB of images plus the BuildKit cache (`docker builder prune` frees it).
- Playground 1.x (Nov 2026) is a rewrite without locomotion tasks, so 0.2.0 is pinned. warp-lang stays at 1.12.0
  (1.19 dropped an API MJX 3.6 imports).
- Isaac Lab fetches task assets from NVIDIA's Omniverse content at run time (relevant for P6.12, no-egress jobs).
