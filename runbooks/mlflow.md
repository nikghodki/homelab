# MLflow (plan P6.5, interim before k3s)

Experiment tracking for the sim jobs (and anything else that trains). For now it's a Docker stack on dgx-2; the k3s
target is the `sim` namespace, with PostgreSQL on CNPG and artifacts on SeaweedFS (S3), both later.

| Piece | Where |
|---|---|
| Stack `ml` | dgx-2 `/opt/homelab/ml`, from `hosts/stacks/ml`, deployed by `hosts/playbooks/ml.yml` |
| MLflow 3.18.0 | `mlflow`, image `homelab/mlflow:3.18.0-psycopg2.9.13`, built on dgx-2 from `hosts/stacks/ml/mlflow` (official `ghcr.io/mlflow/mlflow:v3.18.0`, pinned, plus `psycopg2-binary` with hashes; runs as uid 1000). **No published port** |
| PostgreSQL 17 | `postgresql`, its own instance (not the Temporal one), database `mlflow`, volume `ml_pg-data`; not published |
| Artifacts | volume `ml_artifacts` at `/mlartifacts`, served by MLflow (`--serve-artifacts`): clients upload and download through the server (`mlflow-artifacts:/...`), never the volume |
| Browser | **https://mlflow.nghodki.ai** → dgx-1 Caddy → oauth2-proxy on **192.168.86.36:4181** (LAN) → `mlflow:5000` |
| Job API | **http://192.168.86.36:5000** (LAN), a Caddy (`api`) with HTTP basic auth → `mlflow:5000`; `/health` is open |
| Uptime | Gatus group `ml`: `mlflow.nghodki.ai` through the front door (302 to Pocket ID) and `http://192.168.86.36:5000/health` |
| Secrets | `secrets/ml.enc.yaml` (`postgres_password`, `oauth2_proxy_mlflow_cookie_secret`, `mlflow_api_password` and its bcrypt `mlflow_api_password_hash`); `secrets/console.enc.yaml` (`oidc_mlflow_secret`) |

Memory: about 0.6 GiB for MLflow (2 uvicorn workers) and 0.1 GiB for the rest, capped at 1 GiB / 512 MiB / 128 MiB.
MLflow 3's GenAI job runner (online scoring, trace archival) is off (`MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false`): it
starts about nine huey consumers of ~240 MiB each, and experiment tracking doesn't use it.

## Deploy or change

```bash
source ~/.venvs/ansible/bin/activate && cd ~/homelab/hosts
ansible-playbook playbooks/ml.yml --check --diff
ansible-playbook playbooks/ml.yml
```

The playbook waits for `/health` on the job API and writes `/etc/homelab/mlflow-client.env` on dgx-2 (root:docker,
0640) with the job API settings. Upgrades: bump the base image (tag and digest) in `hosts/stacks/ml/mlflow/Dockerfile`
**and** the `image:` tag in `compose.yaml` (compose only builds when the tag is missing), then deploy. MLflow migrates its
schema on start; take a `pg_dump` first if the release notes mention migrations:
`sudo docker compose --project-directory /opt/homelab/ml exec postgresql pg_dump -U mlflow mlflow > /tmp/mlflow.sql`.

The front-door route (`@mlflow` in `~/edge-gateway/conf/Caddyfile`, http → https because the cookie is Secure) and the DNS
entries (`mlflow.nghodki.ai` → 192.168.86.44 and 100.65.137.82 in `~/edge-gateway/dnsmasq/dnsmasq.conf`) live on dgx-1,
outside this repo.

## Who can reach it

- **People:** `https://mlflow.nghodki.ai`, signed in through Pocket ID (client `mlflow`, group `admins`, PKCE; recipe in
  [sign-in.md](sign-in.md)). Signed out, you get a 302 to `id.nghodki.ai`. MLflow itself has no login.
- **Jobs:** the job API on `192.168.86.36:5000`, with basic auth (user `sim`). It isn't open because MLflow has no
  authorization: an open port would let anything on the home LAN delete experiments or upload files. Port 5000 listens
  on the LAN address only, not on dgx-2's Tailscale address; and the Tailscale policy (`policies/tailscale/policy.hujson`)
  grants tags nothing on dgx-2 but 4317–4320 and 8000, so `tag:robot` and `tag:agent` couldn't reach it there anyway, and
  family and guests can't reach dgx-2 at all. Basic auth is over plain HTTP on the LAN: treat the password as
  a LAN-only shared secret (rotate it if it leaks: new value + bcrypt hash in SOPS, redeploy, done).
- The `/health` path of the job API is open (Gatus).

## How jobs log

MLflow's client reads three variables:

```bash
MLFLOW_TRACKING_URI=http://192.168.86.36:5000
MLFLOW_TRACKING_USERNAME=sim
MLFLOW_TRACKING_PASSWORD=...          # secrets/ml.enc.yaml, mlflow_api_password
MLFLOW_EXPERIMENT_NAME=sim-mujoco     # optional
```

On dgx-2 they're in `/etc/homelab/mlflow-client.env`; the `mujoco` service in `hosts/stacks/sim/compose.yaml` loads that
file (`env_file`, `required: false`), so jobs log when it exists and still run without it. To run without MLflow:
`... run --rm -e MLFLOW_TRACKING_URI= mujoco ...`. Anywhere else on the LAN, get the password from SOPS on dgx-1:
`sops -d --extract '["mlflow_api_password"]' secrets/ml.enc.yaml`.

`robots/sim/mujoco/train_ppo.py` logs, when `MLFLOW_TRACKING_URI` is set: all PPO hyperparameters, env, backend, JAX
version and device as params; every `eval/*` metric, `steps_per_s` (since the previous evaluation) and `wall_s` at each
evaluation; `final/*` (timesteps, wall and JIT time, overall and steady steps/s) at the end; `summary.json`; and the
policy parameters (Brax `save_params` pickle) as the artifact `policy/policy_params.pkl`. A failed MLflow call prints a
line and turns logging off; it never stops training. A crashed run is marked `FAILED`.

Test run (2026-11-15): `robots/sim/measure.sh mujoco --timesteps 20000000`, run `7c47fb73fb9042c18675203f4b759859`
in experiment `sim-mujoco` (id 1), 174 s: eval reward 0 → 18.87 at 26.2 M steps, 182 k steps/s overall, 221 k steady,
20.8 s JIT; artifact 1.7 MB.

## Retention and backups

None yet: runs and artifacts are kept until someone deletes them (`mlflow gc` after deleting runs in the UI frees the
artifacts). Backups are off for now ([decision 0002](../decisions/0002-backups-off-for-now.md)); `ml_pg-data` and
`ml_artifacts` are not backed up, so a lost disk loses the run history. Keep anything that matters (a policy you
deploy) in the repo or a model registry PR as well.

## Later (k3s)

- Namespace `sim`: MLflow as a Deployment, PostgreSQL on CNPG, artifacts on SeaweedFS's S3 API
  (`--artifacts-destination s3://mlflow/`), still proxied by MLflow so clients need no S3 credentials.
- Sign-in stays oauth2-proxy + Pocket ID; the job API becomes a ClusterIP Service for in-cluster jobs (NetworkPolicy
  from the `sim` namespace) instead of a LAN port.
- Move the two volumes with `pg_dump`/`pg_restore` and a copy of `/mlartifacts` to the bucket (same relative paths).
