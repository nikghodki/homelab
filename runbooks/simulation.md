# Simulation on dgx-2 (plan P6.2, P6.4)

Isaac Lab 3.0 and MuJoCo Playground run as on-demand containers on **dgx-2** only (dgx-1 serves models). The jobs
are services of `hosts/stacks/sim/compose.yaml` in the `jobs` profile: they never start on their own
(`restart: "no"`), are capped at 16 GiB of cgroup memory, drop all capabilities and are removed when they exit.

| Service | Image | What |
|---|---|---|
| `isaaclab` | `homelab/isaaclab:3.0.0-kitless-mlflow3.18.0`, built locally from `robots/sim/isaaclab`: NVIDIA's `nvcr.io/nvidia/isaac-lab:3.0.0-kitless@sha256:d47169952b55effb46dba8f79761d381532b521561ecba38a3019adc7648884b` (NGC, multi-arch) plus only the MLflow client | Isaac Lab 3.0.0, Newton physics, headless, no Isaac Sim ([README](../robots/sim/isaaclab/README.md)) |
| `mujoco` | `homelab/mujoco-playground:0.2.0-jax0.9.2-mlflow3.18.0`, built locally from `robots/sim/mujoco` ([README](../robots/sim/mujoco/README.md)) | MuJoCo 3.6 + MJX + Playground 0.2.0, JAX 0.9.2 on CUDA 13, Brax PPO |

Images live only in dgx-2's local Docker; nothing is pushed. Local image ID of the build measured below:
`homelab/mujoco-playground:0.2.0-jax0.9.2` = `sha256:e094ad5add01c7365722508a2467b0afa50cedcdabd71b114e48850bc61a038e`.
The current tag adds the MLflow client (`mlflow-skinny` 3.18.0, its own layer on top; only additions in `pip freeze`):
`homelab/mujoco-playground:0.2.0-jax0.9.2-mlflow3.18.0` = `sha256:65713a88e6ca8f9dfc961107c3f921665af1e8f74dd7a35e4f9f821a22c99719`
(base `python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`; the full
`pip freeze` is in the image at `/opt/pip-freeze.txt`). Pip resolves unpinned transitive dependencies at build time,
so a rebuild can produce a different ID; compare `/opt/pip-freeze.txt` if results change.

`homelab/isaaclab:3.0.0-kitless-mlflow3.18.0` = `sha256:1615575841a0d3eec7fc9f3c15df5093c65351efed1abf66f75143e485eecef2`
(2026-11-15): one layer on NVIDIA's image adding `mlflow-skinny` 3.18.0 and its 21 dependencies (pydantic 2.14.3,
fastapi 0.163.1, opentelemetry 1.45.2, databricks-sdk 0.156.0, ...). Every package already in NVIDIA's venv is held
at its version by a constraints file made from its `pip freeze`, and the build fails if any of them changed (NVIDIA's
image already fails `pip check`, so that can't be the guard); the result is in `/opt/isaaclab-venv/pip-freeze.txt`.
The training wrapper `robots/sim/isaaclab/train_mlflow.py` is mounted read-only, not copied, so it changes without a
rebuild.

## Run

From dgx-1, copy the two folders to dgx-2 (the compose file builds from `../../../robots/sim/mujoco`):

```bash
cd ~/homelab && git pull
rsync -aR --delete ./hosts/stacks/sim ./robots/sim nikghodki-dgx-2@192.168.86.36:sim-repo/
ssh nikghodki-dgx-2@192.168.86.36
cd ~/sim-repo
df -h /                                    # keep at least 15% free
docker compose -f hosts/stacks/sim/compose.yaml --profile jobs build isaaclab   # pulls NVIDIA's image (5.3 GB download, 16.3 GB on disk), adds ~0.1 GB
docker compose -f hosts/stacks/sim/compose.yaml --profile jobs build mujoco     # ~6 min, 12.4 GB on disk
```

Smoke tests (each a few minutes; `measure.sh` prints GPU utilisation, GPU memory, cgroup peak and the lowest host
MemAvailable, and stops the job if MemAvailable drops below `SIM_MIN_AVAIL_GIB`, default 8):

```bash
robots/sim/measure.sh isaaclab train --rl_library rsl_rl --task Isaac-Cartpole-Direct --max_iterations 1000 physics=newton_mjwarp
robots/sim/measure.sh isaaclab train --rl_library rsl_rl --task Isaac-Velocity-Flat-AnymalD --max_iterations 200 physics=newton_mjwarp
robots/sim/measure.sh mujoco                                   # Go1JoystickFlatTerrain, MJX warp backend, ~26M steps
robots/sim/measure.sh mujoco --impl jax --timesteps 10000000   # same task, pure-JAX MJX
```

Both jobs log to MLflow when `/etc/homelab/mlflow-client.env` exists on dgx-2, which `playbooks/ml.yml` writes: MuJoCo
to experiment `sim-mujoco` (params, eval reward, steps/s, the policy), Isaac Lab RSL-RL to `sim-isaaclab` (params,
every iteration's reward, episode length, losses and steps/s, the final checkpoint). `measure.sh` then adds its GPU and
memory numbers to the same run (`measure/*`). Details in [mlflow.md](mlflow.md). `-e MLFLOW_TRACKING_URI=` on
`docker compose ... run` turns it off for one run (Isaac Lab then writes TensorBoard files only, as before).

Logs and 2-second samples go to `/tmp/sim-<service>-<epoch>.{log,samples.csv}`. Isaac Lab checkpoints are in the
`sim_isaaclab-logs` volume. Without `measure.sh`:
`docker compose -f hosts/stacks/sim/compose.yaml --profile jobs run --rm isaaclab [isaaclab args]`.

## Results (2026-11-15, dgx-2, DGXMM's Qwen3.8 engine loaded and idle)

GPU utilisation is the whole GB10 (`nvidia-smi`, 2 s samples, startup included in the mean). GPU memory is the
job's own processes in `nvidia-smi --query-compute-apps`; on the GB10 it comes out of the same unified memory but is
not charged to the container's cgroup.

| Run | Envs | Steps | Train time | Throughput | GPU util mean / max | Job GPU mem | cgroup peak | Host MemAvailable min |
|---|---|---|---|---|---|---|---|---|
| Isaac Lab `Isaac-Cartpole-Direct`, RSL-RL PPO, 1000 iterations | 4096 | 65.5 M | 137 s | 487 k steps/s (median) | 17% / 39% | 371 MiB | 3.1 GiB | 25.1 GiB (from 27.5) |
| Isaac Lab `Isaac-Velocity-Flat-AnymalD`, RSL-RL PPO, 200 iterations | 4096 | 19.7 M | 221 s | 98 k steps/s (median) | 63% / 92% | 1.2 GiB | 3.2 GiB | 24.2 GiB |
| Playground `Go1JoystickFlatTerrain`, Brax PPO, MJX `warp` | 8192 | 26.2 M | 164 s (20 s JIT) | 183 k steps/s overall, 224 k steady | 68% / 96% | 2.5 GiB | 2.5 GiB | 23.1 GiB |
| Playground `Go1JoystickFlatTerrain`, Brax PPO, MJX `jax` | 8192 | 13.1 M | 205 s (53 s JIT) | 180 k steps/s steady | 35% / 96% | 2.4 GiB | 3.1 GiB | 22.5 GiB |

Learning is real, not just stepping: Cartpole ends at success rate 1.0 and the full 300-step episode length; Go1's eval
reward goes 0 → 19.6 in 20 M steps. Cartpole is too small to load the GPU (kernel-launch bound).

Notes:
- Isaac Lab 3.0 has no `--headless` flag (kit-less runs are headless unless `--viz` is given). Isaac Lab 3.0 ships
  no wheeled-robot task (no Jetbot/Leatherback in `isaaclab list_envs`); Anymal-D flat locomotion stands in as the
  ground-robot example until our own robot task (P6.1, P6.7) exists.
- XLA prints `xtile_compiler.cc` errors while autotuning GEMM fusions on the GB10; they are failed autotune
  candidates, training continues.
- Isaac Sim (P6.3): `nvcr.io/nvidia/isaac-sim:6.2.0` (9.3 GB compressed, arm64) and the full
  `nvcr.io/nvidia/isaac-lab:3.0.0` (14.9 GB) exist for arm64; NVIDIA's requirements page lists DGX Spark as the only
  supported aarch64 system (cuRobo/cuMotion not supported). Not pulled or tested.

## Memory budget

dgx-2 has 121 GiB of unified memory. With DGXMM's engine loaded it had ~27 GiB MemAvailable before any job. Plan
P2.7 keeps 15–23 GiB for dgx-2's services (observe, console, gpu, Temporal); these smoke tests used at most ~5 GiB
(cgroup + GPU) and never took MemAvailable below 22.5 GiB.

- Every job: `mem_limit: 16g` (CPU side). CUDA memory is outside the cgroup, so cap it per framework: JAX
  `XLA_PYTHON_CLIENT_MEM_FRACTION=0.15` (~18 GiB; never leave JAX's default 75% preallocation on a shared Spark),
  Isaac Lab via `--num_envs`.
- Run one job at a time, and only when `free -g` shows room above the reserve. `measure.sh`'s watchdog
  (`SIM_MIN_AVAIL_GIB`) is the backstop; raise it if DGXMM changes what it keeps loaded.
- Bigger runs (more envs, Isaac Sim rendering) need a DGXMM budget entry first (P6.6).

## Disk

16.4 GB (Isaac Lab kit-less + MLflow client) + 12.5 GB (MuJoCo image) + the BuildKit cache from building the MuJoCo image
(`docker builder du`; `docker builder prune` frees it, the next build then downloads ~4 GB of wheels again).
After these tests the root disk was 15% used.

## Next

- P6.5: MLflow is up ([mlflow.md](mlflow.md)); MuJoCo and Isaac Lab RSL-RL runs and `measure.sh`'s footprint log to it.
  Still to do: a policy video (`MUJOCO_GL=egl` is set in the MuJoCo image; Isaac Lab needs `--video`, which wants a
  renderer the kit-less image doesn't have), and skrl/rl_games runs (the wrapper only hooks RSL-RL).
- P6.6: sim jobs in the GPU queue with these footprints (Isaac Lab ~3 GiB + 0.4–1.2 GiB GPU; Playground Go1
  ~3 GiB + 2.5 GiB GPU at 8192 envs); DGXMM budget; Temporal train → eval → export → register → PR.
- P6.3: pull `isaac-sim:6.2.0` and test camera/LiDAR rendering; P6.12: Trivy-scan both images and block egress
  from job containers (Playground needs none at run time; Isaac Lab fetches task assets from NVIDIA's Omniverse content S3/CloudFront at run time).
