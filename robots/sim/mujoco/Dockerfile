# MuJoCo + MJX + MuJoCo Playground on JAX/CUDA 13, for the DGX Sparks (GB10, linux/arm64). Plan P6.4.
# Playground 0.2.0 is the last MJX/JAX release with the locomotion suite (Go1, Spot, G1, ...);
# Playground 1.x is a rewrite on MuJoCo Warp + PyTorch/RSL-RL without locomotion tasks.
# JAX ships CUDA 13 wheels for linux-aarch64 (jax-cuda13-plugin/pjrt); the CUDA libraries come from
# pip (nvidia-*-cu13), so the base image needs no CUDA toolkit, only the host driver (580+).
FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ARG JAX_VERSION=0.9.2
ARG MUJOCO_VERSION=3.6.0
ARG PLAYGROUND_VERSION=0.2.0
ARG BRAX_VERSION=0.14.2
# MJX 3.6 imports warp._src.jax_experimental.ffi.GraphMode, which warp-lang 1.19 no longer has.
ARG WARP_VERSION=1.12.0

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    MUJOCO_GL=egl

# git: Playground fetches MuJoCo Menagerie (pinned commit) on first use; done below at build time.
# libegl1/libgl1: offscreen rendering for videos (P6.5).
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates libegl1 libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

RUN pip install \
      "jax[cuda13]==${JAX_VERSION}" \
      "mujoco==${MUJOCO_VERSION}" \
      "mujoco-mjx==${MUJOCO_VERSION}" \
      "playground==${PLAYGROUND_VERSION}" \
      "brax==${BRAX_VERSION}" \
      "warp-lang==${WARP_VERSION}" \
 && pip freeze > /opt/pip-freeze.txt

# MLflow client (plan P6.5): train_ppo.py logs runs when MLFLOW_TRACKING_URI is set. A separate layer, so the
# JAX/MuJoCo layer above stays cached; the skinny client has no server or UI. pip check guards against a dependency
# it would downgrade.
ARG MLFLOW_VERSION=3.18.0
RUN pip install "mlflow-skinny==${MLFLOW_VERSION}" \
 && pip check \
 && pip freeze > /opt/pip-freeze.txt

# Fetch Menagerie into the package now, so jobs need no egress for robot assets (plan P6.12).
RUN JAX_PLATFORMS=cpu python -c "from mujoco_playground._src import mjx_env; mjx_env.ensure_menagerie_exists()"

COPY train_ppo.py /opt/sim/train_ppo.py

RUN useradd --create-home --uid 1000 sim
USER 1000:1000
RUN mkdir -p /home/sim/.cache
WORKDIR /home/sim
HEALTHCHECK NONE
ENTRYPOINT ["python", "/opt/sim/train_ppo.py"]
