---
title: "Services"
description: "Every service in the fleet in one table: URL, host, port, how it is deployed, its health check and what it depends on."
---

| Service | URL | Host | Port(s) | Deployed by | Health check | Page |
|---|---|---|---|---|---|---|
| LiteLLM | `model.nghodki.ai`, `litellm-admin.nghodki.ai` | dgx-1 | 4000 | hand (`~/litellm-setup`) | Gatus `model.nghodki.ai (LiteLLM)` | [LiteLLM](litellm.md) |
| DGXMM | `dgxmanager.nghodki.ai` | dgx-1 | 127.0.0.1:8090 | DGXMM project | Gatus `dgxmanager.nghodki.ai` | [Model plane](../agents/model-plane.md) |
| Open WebUI | `webui.nghodki.ai` | dgx-1 | 3100 | hand | Gatus `webui.nghodki.ai` | [Open WebUI](open-webui.md) |
| NATS | `nats.nghodki.ai` | dgx-1 | 4222, 8883 | `bus.yml` | Gatus `NATS (TLS)`, `NATS MQTT` | [NATS](nats.md) |
| Fleet broker and API | `fleet.nghodki.ai` | dgx-1 | 8884, 8971 | `fleet.yml` | Gatus `Fleet MQTT`, `Fleet API` | [Fleet broker](fleet-broker.md) |
| Pocket ID | `id.nghodki.ai` | dgx-2 | 1411 | `console.yml` | Homepage monitor `/healthz` | [Pocket ID](pocket-id.md) |
| Homepage | `ops.nghodki.ai` | Dell | 4180 | `ops.yml` | Gatus `ops.nghodki.ai` (302) | [Homepage](homepage.md) |
| Docs site | `docs.nghodki.ai` | Dell | 4181 | `ops.yml` (role `docs_site` + stack `ops`) | Gatus `docs.nghodki.ai` (302), `docs build` | [Docs site](docs-site.md) |
| Grafana, VictoriaMetrics, Loki, Tempo, vmalert, Alertmanager | `grafana.nghodki.ai` | dgx-2 | 3000 (+ internal) | `observe.yml` | Gatus `Grafana`, heartbeat | [Observe stack](observe-stack.md) |
| Phoenix | `phoenix.nghodki.ai` | dgx-2 | 6006 | `observe.yml` | Gatus `Phoenix` | [Phoenix](phoenix.md) |
| Gatus, ntfy | `status.nghodki.ai`, `ntfy.nghodki.ai` | Dell | 8081, 8085 | `alerting.yml` | dead man `AlertingHostDown` | [Gatus and ntfy](gatus-ntfy.md) |
| Temporal | `temporal.nghodki.ai` | dgx-2 | 7233, 8233, 9233 | `jobs.yml` | Gatus `Temporal frontend`, `temporal.nghodki.ai` | [Temporal](temporal.md) |
| MLflow | `mlflow.nghodki.ai` | dgx-2 | 4181, 5000 | `ml.yml` | Gatus `mlflow.nghodki.ai`, `MLflow job API` | [MLflow](mlflow.md) |
| Home Assistant | `ha.nghodki.ai` | Jetson | 8123 | hand (container) | Gatus `Home Assistant (direct)`, `ha.nghodki.ai` | [Home Assistant](home-assistant.md) |
| LiveKit, control center (voice retired, D26) | `controlcenter.nghodki.ai` | Jetson | 127.0.0.1:7880, 8200 | hand | none | [Voice](voice.md) |
| restic rest-server | `backup.nghodki.ai:8000` | dgx-2 | 8000 | `backups.yml` | none | [Backup server](backup-server.md) |
| Zenoh router | — | Jetson | 7447 | `robot.yml` | Gatus `Zenoh router` | [ROS 2 and Zenoh](../robotics/ros-zenoh.md) |
| Safety governor | — | Pi | 127.0.0.1:9113 | `robot.yml` | `SafetyGovernorStatusStale` | [Safety governor](../robotics/safety-governor.md) |
| Hermes | (A2A later) | Jetson | 8642, 8643 | hand | none | [Hermes](../agents/hermes.md) |
| picoclaw | — | Pi | — | hand | none | [picoclaw](../agents/picoclaw.md) |
| k3s platform (Argo CD, Kyverno, CNPG) | `argocd.nghodki.ai` | Sparks | — | Argo CD | Gatus `API ...`, `etcd ...`; gitops alerts | [Platform](../platform/index.md) |

Every web UI also has a tile on Homepage (`hosts/stacks/ops/homepage/services.yaml`).
