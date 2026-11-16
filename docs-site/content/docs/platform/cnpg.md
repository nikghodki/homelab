---
title: "CloudNativePG"
description: "The Postgres operator in k3s, its first cluster (LiteLLM's litellm-db, since 2026-11-16), and the plan for the rest."
---

CloudNativePG operator 1.30.1 (chart `cloudnative-pg` 0.29.1) runs in `cnpg-system`, one replica on the Sparks
(requests 64Mi, limit 256Mi, about 22 MiB used). It watches all namespaces (`clusterWide: true`). No PodMonitor, no
Grafana dashboard. Values: `cluster/platform/cnpg-operator/values.yaml`; app `cnpg-operator` (no resources finalizer, so
deleting the Application never deletes the CRDs and with them every Postgres cluster).

## `data/litellm-db` (LiteLLM, since 2026-11-16)

| | |
|---|---|
| Manifests | `cluster/apps/data/litellm-db.yaml` (Argo CD app `data`, namespace `data`) |
| Instances | 2, Postgres 17.12 (`ghcr.io/cloudnative-pg/postgresql:17.12-standard-trixie`, by digest): primary placed on dgx-2, standby on dgx-1 (required anti-affinity), asynchronous streaming |
| Resources | 10 Gi local-path per instance; requests 256 Mi, limit 1 Gi |
| Address | the primary at the fixed ClusterIP `10.43.0.151:5432` (`data/litellm-db-host`) |
| Who may connect | NetworkPolicy `litellm-db`: the LiteLLM pods, the instances, the operator, and host processes on the Sparks (the usage exporter on dgx-1) |
| Owner | `litellm` (Secret `litellm-db-app`, KSOPS `cluster/apps/data/litellm-db.enc.yaml`) |
| Backups | `pg_dump` from the primary before dgx-1's restic run (`/var/backups/homelab/litellm-db.sql.gz`); no WAL archiving yet (P3.8) |
| Monitoring | no PodMonitor |

After a failover the primary stays where it went; `kubectl -n data get cluster litellm-db` shows where it is. Shell,
restore and switchover: `runbooks/litellm.md`. The data came from the Docker Postgres 16 by `pg_dump` and
`pg_restore --single-transaction` at the cutover; the stopped `litellm-postgres` on dgx-1 keeps the data as of then,
the rollback until 2026-11-23.

## Still in Docker

| Database | Where | Target (P3.7) |
|---|---|---|
| Temporal | `jobs-postgresql-1` on dgx-2 (databases `temporal`, `temporal_visibility`) | CNPG |
| MLflow | `ml-postgresql-1` on dgx-2 (database `mlflow`) | CNPG, artifacts on SeaweedFS |

The plan (architecture §11) is continuous WAL archiving to SeaweedFS (30 days) once SeaweedFS exists (P3.8).

Add a cluster: a `Cluster` manifest in `cluster/apps/<name>/` (namespace `data`), with requests, limits and a
`nodeSelector`, its credentials as a SOPS Secret, and an Application in project `apps`. Upgrade the operator by bumping
`targetRevision` in `cluster/bootstrap/apps/cnpg-operator.yaml`.
