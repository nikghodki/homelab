---
title: "CloudNativePG"
description: "The Postgres operator in k3s: installed, no clusters yet, and the plan for it."
---

CloudNativePG operator 1.30.1 (chart `cloudnative-pg` 0.29.1) runs in `cnpg-system`, one replica on the Sparks
(requests 64Mi, limit 256Mi, about 22 MiB used). It watches all namespaces (`clusterWide: true`). No PodMonitor, no
Grafana dashboard. Values: `cluster/platform/cnpg-operator/values.yaml`; app `cnpg-operator` (no resources finalizer, so
deleting the Application never deletes the CRDs and with them every Postgres cluster).

**No Postgres clusters exist yet.** Every database today is a container in a Docker stack:

| Database | Where | Target (P3.7) |
|---|---|---|
| LiteLLM | `litellm-postgres` on dgx-1 (hand-run, 127.0.0.1:5432) | CNPG in `data`, primary dgx-2, standby dgx-1 |
| Temporal | `jobs-postgresql-1` on dgx-2 (databases `temporal`, `temporal_visibility`) | CNPG |
| MLflow | `ml-postgresql-1` on dgx-2 (database `mlflow`) | CNPG, artifacts on SeaweedFS |

The plan (architecture §11) is continuous WAL archiving to SeaweedFS (30 days) once SeaweedFS exists (P3.8).

Add a cluster: a `Cluster` manifest in `cluster/apps/<name>/` (namespace `data`), with requests, limits and a
`nodeSelector`, its credentials as a SOPS Secret, and an Application in project `apps`. Upgrade the operator by bumping
`targetRevision` in `cluster/bootstrap/apps/cnpg-operator.yaml`.
