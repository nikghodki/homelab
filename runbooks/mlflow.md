# MLflow (plan P6.5, interim before k3s)

Experiment tracking for the sim jobs (and anything else that trains). For now it's a Docker stack on dgx-2; the k3s
target is the `sim` namespace, with PostgreSQL on CNPG and artifacts on SeaweedFS (S3), both later.

| Piece | Where |
|---|---|
| Stack `ml` | dgx-2 `/opt/homelab/ml`, from `hosts/stacks/ml`, deployed by `hosts/playbooks/ml.yml` |
| MLflow 3.18.0 | `mlflow`, image `homelab/mlflow:3.18.0-psycopg2.9.13`, built on dgx-2 from `hosts/stacks/ml/mlflow` (official `ghcr.io/mlflow/mlflow:v3.18.0`, pinned, plus `psycopg2-binary` with hashes; runs as uid 1000). **No published port** |
| PostgreSQL 17 | `postgresql`, its own instance (not the Temporal one), database `mlflow`, volume `ml_pg-data`; not published |
| Artifacts | volume `ml_artifacts` at `/mlartifacts`, served by MLflow (`--serve-artifacts`): clients upload and download through the server (`mlflow-artifacts:/...`), never the volume |
| Browser | **https://mlflow.nghodki.ai** → the front door (sign-in: `edge-auth`, admins, [sign-in.md](sign-in.md)) → the ml stack's Caddy on **192.168.86.36:4181** (LAN; needs the door's `X-Edge-Origin` token, else 403) → `mlflow:5000` |
| Job API | **http://192.168.86.36:5000** (LAN), a Caddy (`api`) with HTTP basic auth → `mlflow:5000`; `/health` is open |
| Uptime | Gatus group `ml`: `mlflow.nghodki.ai` through the front door (302 to Pocket ID) and `http://192.168.86.36:5000/health` |
| Launcher | Homepage (`https://ops.nghodki.ai`, group ML): links to `mlflow.nghodki.ai`; its status dot checks the job API's open `/health`, since the browser URL answers 302 when signed out |
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

On dgx-2 they're in `/etc/homelab/mlflow-client.env`; the `mujoco` and `isaaclab` services in `hosts/stacks/sim/compose.yaml` load that
file (`env_file`, `required: false`), so jobs log when it exists and still run without it. To run without MLflow:
`... run --rm -e MLFLOW_TRACKING_URI= mujoco ...` (or `isaaclab`). Anywhere else on the LAN, get the password from SOPS on dgx-1:
`sops -d --extract '["mlflow_api_password"]' secrets/ml.enc.yaml`.

`robots/sim/mujoco/train_ppo.py` logs, when `MLFLOW_TRACKING_URI` is set: all PPO hyperparameters, env, backend, JAX
version and device as params; every `eval/*` metric, `steps_per_s` (since the previous evaluation) and `wall_s` at each
evaluation; `final/*` (timesteps, wall and JIT time, overall and steady steps/s) at the end; `summary.json`; and the
policy parameters (Brax `save_params` pickle) as the artifact `policy/policy_params.pkl`. A failed MLflow call prints a
line and turns logging off; it never stops training. A crashed run is marked `FAILED`.

### Isaac Lab (RSL-RL)

The `isaaclab` service runs `robots/sim/isaaclab/train_mlflow.py`, which takes the `isaaclab` command's arguments and
runs it in-process. Isaac Lab 3.0's own `logger` setting only offers tensorboard, wandb and neptune, but RSL-RL 5.5
takes any `LogWriter` class in the runner config's `logger`; the wrapper puts its `MlflowLogWriter` there (it is also a
TensorBoard `SummaryWriter`, so the event files in `sim_isaaclab-logs` stay). With `MLFLOW_TRACKING_URI` set it logs to
experiment `sim-isaaclab` (or `MLFLOW_EXPERIMENT_NAME`), run name `<task>-<iterations>it`:

- params: the runner config flattened (`algorithm.*`, `actor.*`, `max_iterations`, `num_steps_per_env`, `seed`, ...),
  task, `num_envs`, physics preset, `sim.dt`, decimation, episode length and package versions; tags `sim.*` (task,
  argv, log dir); the full configs as `config/agent.json` and `config/env.json`, Isaac Lab's `params/*.yaml`;
- every iteration (step = iteration), batched into one request per iteration: `Train/mean_reward`,
  `Train/mean_episode_length`, `Perf/total_fps` (environment steps/s), `Perf/collection_time`, `Perf/learning_time`,
  `Loss/*`, `Policy/mean_std` and the task's `Episode/*` or `Metrics/*` (Cartpole: `Metrics/success_rate`);
- at the end: `final/*` (iterations, timesteps, wall, median and last steps/s, mean reward and episode length),
  `summary.json`, and the final checkpoint `checkpoint/model_<it>.pt` (intermediate checkpoints stay in the volume).

As in `train_ppo.py`, a failed MLflow call prints one line and turns logging off; training continues. A run that
crashes ends `FAILED`; one stopped by `docker stop` (or `measure.sh`'s watchdog: the wrapper handles SIGTERM, which
PID 1 otherwise ignores) ends `KILLED`. skrl, rl_games and sb3 runs aren't hooked.

### measure.sh

When the job printed `mlflow: run <id> in experiment <id>` (both training scripts do) and the client env file is
readable (`SIM_MLFLOW_ENV`, default `/etc/homelab/mlflow-client.env`), `robots/sim/measure.sh` adds to **that same
run**, after the job exits: metrics `measure/gpu_util_mean_pct`, `measure/gpu_util_max_pct`,
`measure/job_gpu_mem_peak_mib`, `measure/container_mem_peak_mib` (cgroup `memory.peak`),
`measure/host_mem_available_min_gib`, `measure/host_mem_available_start_gib`, `measure/wall_s`, `measure/samples`;
tags `measure.host`, `measure.job`, `measure.exit_code`, `measure.watchdog_stopped`, `measure.min_avail_gib`; and the
2-second samples as `measure/samples.csv`. It uses Python's standard library on the host and the REST API, reading the
credentials from the file itself (never on a command line). If MLflow fails, it says so and keeps the job's exit code.

Why the same run and not a separate "measurement" run: a run is one training job, and its footprint belongs next to
its reward and steps/s (compare and sort runs by memory in one table, no joins by tag). MLflow accepts metrics on a
finished run. The cost is that the run's `end_time` is the training's, and measure-only numbers have step 0. A job
without MLflow (or that failed before starting its run) prints no run ID, and then nothing is logged.

### Test runs

Test run (2026-11-15): `robots/sim/measure.sh mujoco --timesteps 20000000`, run `7c47fb73fb9042c18675203f4b759859`
in experiment `sim-mujoco` (id 1), 174 s: eval reward 0 → 18.87 at 26.2 M steps, 182 k steps/s overall, 221 k steady,
20.8 s JIT; artifact 1.7 MB.

With measure.sh logging (2026-11-15; dgx-2 had ~114 GiB MemAvailable before each job):

| Run | Experiment | Result | measure/* |
|---|---|---|---|
| `e0a346b25bab472bbf7e010036339ca2` `Isaac-Cartpole-Direct-300it` (`measure.sh isaaclab train --rl_library rsl_rl --task Isaac-Cartpole-Direct --max_iterations 300 physics=newton_mjwarp`) | `sim-isaaclab` (2) | 300 iterations, 19.7 M steps in 60 s; reward 0.13 → 4.96, episode length 300, success rate 1.0; 508 k steps/s median, 729 k last; 300 points per metric; checkpoint 46 kB | GPU util 9% mean / 37% max, job GPU 371 MiB, cgroup peak 3.7 GiB, MemAvailable min 112.1 GiB |
| `aaac92eca21e4b3a9e9234fa78b90ef0` `Go1JoystickFlatTerrain-warp-10M` (`measure.sh mujoco --timesteps 10000000`) | `sim-mujoco` (1) | 13.1 M steps in 112 s (20.6 s JIT); eval reward 0 → 15.67; 145 k steps/s overall, 202 k steady; policy 1.7 MB | GPU util 53% mean / 96% max, job GPU 2.5 GiB, cgroup peak 3.5 GiB, MemAvailable min 109.7 GiB |

## Retention and backups

None yet: runs and artifacts are kept until someone deletes them (`mlflow gc` after deleting runs in the UI frees the
artifacts). Backups are off for now ([decision 0002](../decisions/0002-backups-off-for-now.md)); `ml_pg-data` and
`ml_artifacts` are not backed up, so a lost disk loses the run history. Keep anything that matters (a policy you
deploy) in the repo or a model registry PR as well.

## Later (k3s)

- Namespace `sim`: MLflow as a Deployment, PostgreSQL on CNPG, artifacts on SeaweedFS's S3 API
  (`--artifacts-destination s3://mlflow/`), still proxied by MLflow so clients need no S3 credentials.
- Sign-in stays the front door's (`import signed_in`, pointing at a Service); the job API becomes a ClusterIP Service for in-cluster jobs (NetworkPolicy
  from the `sim` namespace) instead of a LAN port.
- Move the two volumes with `pg_dump`/`pg_restore` and a copy of `/mlartifacts` to the bucket (same relative paths).
