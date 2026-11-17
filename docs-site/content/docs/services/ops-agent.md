---
title: "Ops agent"
description: "The ambient ops agent in shadow mode: what it watches, how it investigates, where its RCAs and notifications go, and how to stop it."
---

The ambient operations agent (decision 0013, `docs/ambient-agent-design.md`, `runbooks/ops-agent.md`). **Shadow
mode**: it watches, investigates with read-only tools and the local model, writes root-cause analyses into its own
database and notifies on its own ntfy topic. It changes nothing.

| | |
|---|---|
| Portal | `https://ops-agent.nghodki.ai` (front-door sign-in, admins): Feed, Incident, Replay, Audit, Stop |
| Runs | k3s namespace `ops`: `ops-ingest`, `ops-worker`, `ops-portal` (2 each, one per Spark), CNPG `ops-db`, three read-only MCP servers |
| Workflows | Temporal on dgx-2, namespace `ops-agent` (mTLS, writer on that namespace only) |
| Model | `qwen3.8-27b` through LiteLLM, key `ops-agent`; 1 M tokens a day, 2 investigations at once |
| Inputs | every Alertmanager alert (a receiver with `continue: true`; the ntfy path is unchanged), Gatus results, Kubernetes Warning events, merges and Argo CD syncs, CI failures, log-error baselines |
| Tools (read-only) | metrics and logs (mcp-grafana), the cluster (kubernetes-mcp-server, no Secrets), Argo CD (readonly account), host commands as `opsro` (allowlist), CI runs, runbook search, past incidents |
| Notifications | ntfy topic `ops-agent`: family-facing incidents at once (also at night), criticals outside 22:30-07:30, the rest in the 08:00 digest. Buttons Open, Snooze, Dismiss; never Approve |
| Watchers | Gatus group `ops-agent` (portal, health, ingest, worker heartbeat); vmalert `ops-agent.yml` |
| Stop | the portal's Stop button, or `mode: stopped` in `cluster/apps/ops/mode.txt` |

On the phone: in the ntfy app, add topic `ops-agent` on the same server as `fleet-alerts`.
