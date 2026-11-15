# MuJoCo + MJX + MuJoCo Playground (plan P6.4)

`Dockerfile` builds `homelab/mujoco-playground:0.2.0-jax0.9.2-mlflow3.18.0` for linux/arm64 (GB10):

| Package | Version | Why |
|---|---|---|
| jax, jaxlib, jax-cuda13-plugin/pjrt | 0.9.2 | CUDA 13 wheels exist for linux-aarch64 (also for 0.12.x) |
| mujoco, mujoco-mjx | 3.6.0 | contemporary with Playground 0.2.0 |
| playground | 0.2.0 | last MJX/JAX release; it has the locomotion suite (Go1, Spot, G1, ...) |
| brax | 0.14.2 | PPO |
| mlflow-skinny | 3.18.0 | MLflow client; own layer on top (plan P6.5) |
| warp-lang | 1.12.0 | MJX's Warp backend; 1.19 dropped `warp._src.jax_experimental.ffi.GraphMode` that MJX 3.6 imports |

Playground **1.x** (November 2026) is a rewrite on MuJoCo Warp + PyTorch + RSL-RL and has no locomotion tasks, so
it does not fit P6.4 today. Isaac Lab's image already carries MuJoCo Warp 3.12 for that route.

`train_ppo.py` runs Brax PPO with Playground's own hyperparameters for an environment, shortened with
`--timesteps`; `--impl warp|jax` picks the MJX backend (Go1 defaults to `warp`). It prints the eval reward at each
evaluation and a JSON line with steps/s. MuJoCo Menagerie is fetched at build time, so jobs need no asset downloads.
With `MLFLOW_TRACKING_URI` set it also logs the run to MLflow (params, metrics, policy artifact;
[runbooks/mlflow.md](../../../runbooks/mlflow.md)); without it, nothing changes.

JAX would take 75% of the unified memory by default; the compose service sets
`XLA_PYTHON_CLIENT_PREALLOCATE=false` and `XLA_PYTHON_CLIENT_MEM_FRACTION=0.15`.

Build and run through `hosts/stacks/sim` (service `mujoco`); see [runbooks/simulation.md](../../../runbooks/simulation.md).
