---
title: "dgx-2"
description: "The second DGX Spark: observability, Pocket ID, Temporal, MLflow, simulation jobs, backup server, k3s server that started the cluster."
---

dgx-2 carries the stateful platform services and the batch work. Its memory is shared between those services and GPU
jobs, so jobs must leave the service reserve alone.

## Hardware and OS

| | |
|---|---|
| Hostname | `nikghodki-dgx-2` |
| Hardware | DGX Spark, GB10, 20 cores, 121 GiB unified, 3.7 TB NVMe (18% used) |
| OS | Ubuntu 24.04.5 LTS (DGX OS) |
| User | `nikghodki-dgx-2` (reach it from dgx-1: `ssh nikghodki-dgx-2@192.168.86.36`) |
| LAN | `wlP9s9` 192.168.86.36 (Wi-Fi) |
| Tailscale | 100.124.175.23, `nikghodki-dgx-2.tail1cb707.ts.net`, `tag:gpu`, `tag:control` |
| Spark cable | 10.100.136.2 (k3s), 10.100.137.2 (RDMA) |

## What runs here

| Stack (`/opt/homelab/<name>`) | Containers | Published on | Playbook |
|---|---|---|---|
| `observe` | victoriametrics, vmalert, alertmanager, loki, tempo, otel-defenseclaw, otel-fleet, grafana, phoenix | 0.0.0.0: 3000 (Grafana), 6006 (Phoenix), 4317–4318 (DefenseClaw OTLP), 4319–4320 (fleet OTLP) | `observe.yml` |
| `console` | pocket-id | 192.168.86.36:1411 | `console.yml` |
| `jobs` | temporal, postgresql, admin-tools, ui | 192.168.86.36: 7233 (gRPC), 8233 (UI), 9233 (metrics) | `jobs.yml` |
| `ml` | mlflow, postgresql, api (Caddy) | 192.168.86.36: 4181 (UI gate for the front door), 5000 (job API) | `ml.yml` |
| `gpu` | dcgm-exporter 4.8.4 | 127.0.0.1:9400 | `gpu.yml` |
| `backup` | rest-server (restic) | 0.0.0.0:8000 (TLS) | `backups.yml` |
| `sim` (on demand) | isaaclab, mujoco (profile `jobs`, never start by themselves) | none | run by hand |

Also seen: a `dgxmm-node-probe` container (DGXMM session's; not in this repo).

systemd: `k3s` (server, `cluster-init`), `otelcol-contrib`, `fleet-metrics`, `tailscaled`, `earlyoom` and
`gpu-oom-guard` (`roles/memory_guard`, as on dgx-1). Timers: `cisco-aibom`, `lynis-audit`, `homelab-backup`,
`homelab-backup-prune` (Sunday 05:00).

## Memory

- Services need about 15–23 GiB (P2.7). A DGXMM engine can be loaded here; on 2026-11-15 one was, leaving about
  27 GiB available before any sim job.
- Sim jobs: `mem_limit: 16g`, JAX `XLA_PYTHON_CLIENT_MEM_FRACTION=0.15`, one job at a time, `robots/sim/measure.sh`
  stops a job when MemAvailable drops under 8 GiB. See [Simulation](../robotics/simulation.md).

## Operate

```bash
ssh nikghodki-dgx-2@192.168.86.36
sudo docker compose --project-directory /opt/homelab/observe ps
sudo docker compose --project-directory /opt/homelab/jobs exec admin-tools temporal operator cluster health
```

Deploy any stack from dgx-1: `cd ~/homelab/hosts && ~/.venvs/ansible/bin/ansible-playbook playbooks/<name>.yml --check --diff`.

## Gotchas

- Its Docker uses the containerd image store, which drops compressed layers, so `docker save` fails. The AIBOM job
  falls back to copying files out of a created container.
- MLflow's job API (5000) has no strong auth; it is published on the LAN address only. Temporal's gRPC (7233) requires mTLS (runbooks/temporal.md).
- If dgx-2 is down, metric alerts stop. Gatus on the Dell still alerts on dgx-2's checks, and the missing Watchdog
  heartbeat alerts after 15 minutes.
- Old volumes `observe_gatus-data` and `observe_ntfy-data` from before the move to the Dell may still be here;
  runbooks/alerting.md says to delete them after a week.
