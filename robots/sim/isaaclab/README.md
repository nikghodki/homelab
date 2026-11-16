# Isaac Lab 3.0 (plan P6.2)

We use NVIDIA's **kit-less** image, which is multi-arch (linux/arm64 runs on the DGX Sparks):

    nvcr.io/nvidia/isaac-lab:3.0.0-kitless@sha256:d47169952b55effb46dba8f79761d381532b521561ecba38a3019adc7648884b

The `Dockerfile` here only adds the MLflow client (`mlflow-skinny` 3.18.0, every existing package held at its version)
as `homelab/isaaclab:3.0.0-kitless-mlflow3.18.0`. `train_mlflow.py` is the service's entrypoint (mounted read-only):
it takes the `isaaclab` command's arguments and, when `MLFLOW_TRACKING_URI` is set, logs RSL-RL runs to MLflow
([runbooks/mlflow.md](../../../runbooks/mlflow.md)).

- Isaac Lab 3.0.0 on Ubuntu 24.04, Python 3.12, PyTorch 2.11.0+cu130, Warp 1.17, Newton 1.6.1, MuJoCo Warp 3.12,
  RSL-RL 5.5.1, skrl 2.1.0. Runs as uid 1000 (`isaaclab`).
- No Isaac Sim inside, so no Isaac Sim EULA and no RTX rendering. Physics is Newton
  (`physics=newton_mjwarp`); it is headless unless you pass `--viz` (there is no `--headless` flag in 3.0).
- Logs and checkpoints: `/workspace/isaaclab/logs` (the `sim_isaaclab-logs` volume).
- Isaac Sim (P6.3, camera/LiDAR rendering): `nvcr.io/nvidia/isaac-sim:6.2.0` and `nvcr.io/nvidia/isaac-lab:3.0.0`
  have arm64 images, and NVIDIA lists DGX Spark as the only supported aarch64 system. Not pulled or tested yet.

Run it through `hosts/stacks/sim` (service `isaaclab`); see [runbooks/simulation.md](../../../runbooks/simulation.md).
