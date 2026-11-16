---
title: "MLflow"
description: "Experiment tracking on dgx-2: MLflow with its own PostgreSQL, a browser path behind Pocket ID and a basic-auth job API."
---

| | |
|---|---|
| Purpose | Experiment tracking for sim jobs (P6.5); later the policy registry |
| Host | dgx-2, stack `ml` (`hosts/stacks/ml`, `playbooks/ml.yml`, `/opt/homelab/ml`) |
| Containers | `mlflow` (3.18.0, image `homelab/mlflow:3.18.0-psycopg2.9.13` built on dgx-2 from `hosts/stacks/ml/mlflow/Dockerfile`, uid 1000, 2 workers, `--serve-artifacts`, no published port), `postgresql` (17, database `mlflow`, volume `ml_pg-data`), `oauth2-proxy`, `api` (Caddy 2.11.9 as 65532, no capabilities) |
| Browser | `https://mlflow.nghodki.ai` → front door → oauth2-proxy 192.168.86.36:4181 → `mlflow:5000`. Pocket ID client `mlflow`, admins |
| Job API | `http://192.168.86.36:5000` (LAN only), basic auth user `sim`; `/health` open |
| Artifacts | volume `ml_artifacts` at `/mlartifacts`, uploaded and downloaded through the server |
| Allowed hosts | `mlflow.nghodki.ai`, `192.168.86.36:5000`, `mlflow:5000`, `localhost:5000` (DNS-rebinding protection) |
| Memory caps | mlflow 1 GiB, postgres 512 MiB, proxy and api 128 MiB; GenAI job runner off (`MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false`) |
| Secrets | `secrets/ml.enc.yaml` → `postgres_password`, `mlflow_api_password`, `mlflow_api_password_hash`, `oauth2_proxy_mlflow_cookie_secret`; `console` → `oidc_mlflow_secret` |
| Client file | `/etc/homelab/mlflow-client.env` on dgx-2 (root:docker, 0640), written by the playbook; sim jobs read it |
| Health | Gatus `mlflow.nghodki.ai` (302) and `MLflow job API` (`/health` = OK); Homepage tile (group ML) checks the job API's `/health` |
| Image signing | also built and signed in CI as `ghcr.io/nikghodki/mlflow` ([Image signing](../platform/image-signing.md)) |
| k3s target | `sim`: Deployment, CNPG Postgres, SeaweedFS artifacts |

## Why two ways in

MLflow has no authorization. An open port would let anything on the LAN delete experiments. People go through Pocket
ID; jobs use basic auth over plain HTTP on the LAN (treat the password as a LAN-only shared secret). Port 5000 is on
dgx-2's LAN address only and isn't granted on Tailscale.

## Jobs

```bash
MLFLOW_TRACKING_URI=http://192.168.86.36:5000
MLFLOW_TRACKING_USERNAME=sim
MLFLOW_TRACKING_PASSWORD=...              # sops -d --extract '["mlflow_api_password"]' secrets/ml.enc.yaml
MLFLOW_EXPERIMENT_NAME=sim-mujoco         # optional
```

`robots/sim/mujoco/train_ppo.py` (experiment `sim-mujoco`) and `robots/sim/isaaclab/train_mlflow.py` (`sim-isaaclab`,
RSL-RL) log params, metrics, a summary and the policy or checkpoint; `robots/sim/measure.sh` adds GPU and memory
footprints (`measure/*`) to the same run ([Simulation](../robotics/simulation.md)). A failed MLflow call turns logging
off; it never stops training. Test run 2026-11-15: experiment `sim-mujoco`, 174 s, eval reward 0 →
18.87 at 26.2 M steps, 182 k steps/s.

## Deploy, upgrade

`ansible-playbook playbooks/ml.yml --check --diff`, then for real (it waits for `/health`). Upgrade: bump the base image
(tag and digest) in the Dockerfile **and** the `image:` tag in `compose.yaml` (compose builds only when the tag is
missing). `pg_dump` first if the release notes mention migrations:
`sudo docker compose --project-directory /opt/homelab/ml exec postgresql pg_dump -U mlflow mlflow > /tmp/mlflow.sql`.

## Retention and backups

None. Runs stay until deleted (`mlflow gc` frees artifacts). Volumes are not backed up (decision 0002): keep anything
that matters in the repo too.
