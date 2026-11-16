# Thin layer on NVIDIA's Isaac Lab 3.0.0 kit-less image: only the MLflow client (plan P6.5), so RSL-RL runs can log
# through robots/sim/isaaclab/train_mlflow.py (mounted by hosts/stacks/sim, not copied, so it changes without a rebuild).
# Everything else is NVIDIA's image unchanged. runbooks/simulation.md, runbooks/mlflow.md.
FROM nvcr.io/nvidia/isaac-lab:3.0.0-kitless@sha256:d47169952b55effb46dba8f79761d381532b521561ecba38a3019adc7648884b

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The venv belongs to the image's user (uid 1000), so no root is needed. NVIDIA's image already fails `pip check`
# (Isaac Sim asset packages pin older versions), so instead every package already installed is held at its version
# (constraints from `pip freeze`): the client may only add packages. The diff check fails the build if anything changed.
ARG MLFLOW_VERSION=3.18.0
RUN pip freeze | grep '==' > /tmp/base-freeze.txt \
 && pip install --constraint /tmp/base-freeze.txt "mlflow-skinny==${MLFLOW_VERSION}" \
 && pip freeze > /opt/isaaclab-venv/pip-freeze.txt \
 && changed="$(comm -23 <(sort /tmp/base-freeze.txt) <(sort /opt/isaaclab-venv/pip-freeze.txt))" \
 && if [ -n "$changed" ]; then echo "changed by the MLflow client: $changed"; exit 1; fi \
 && rm /tmp/base-freeze.txt

USER 1000:1000
HEALTHCHECK NONE
