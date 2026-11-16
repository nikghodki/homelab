---
title: "Dashboards"
description: "Grafana at grafana.nghodki.ai: folders, the Fleet Home, AI inventory and Model API callers dashboards, the Argo CD board, the 19 DefenseClaw dashboards, data sources."
---

Grafana 13.3.1 runs on dgx-2 (`192.168.86.36:3000`), served as `https://grafana.nghodki.ai`. Sign-in is Pocket ID;
`admins` become Grafana Admin, everyone else Viewer. All dashboards are files in Git, provisioned read-only
(`allowUiUpdates: false`, `disableDeletion: true`): change them in a PR, not in the UI.

| Folder | Path in the repo | Dashboards |
|---|---|---|
| Fleet | `hosts/stacks/observe/grafana/dashboards/fleet/` | Fleet Home (home page), AI inventory, Model API callers |
| Cluster | `.../dashboards/cluster/` | Argo CD |
| Security (DefenseClaw) | `.../dashboards/defenseclaw/` | 19 vendored DefenseClaw dashboards |

## Fleet Home (`uid fleet-home`, Grafana's home page)

| Panel | Shows |
|---|---|
| Hosts reporting | how many hosts sent host metrics recently |
| Alerts firing | from `ALERTS`, Watchdog filtered out |
| Memory used, Disk used | bar gauges per host |
| CPU busy, Load (1 min), Network | time series per host |
| Log lines per host (5 min) | from Loki |
| Firing alerts | table |
| GPU busy (Sparks, Jetson) | fleet-metrics |
| Memory used (fleet-metrics; GB10 unified) | the right memory number on the Sparks (DCGM reports GPU memory as N/A on GB10) |
| Row "GPU, temperature and power" | GPU temperature and power (DCGM), hottest sensor per host, Jetson power rails (INA3221) |
| Row "Security hardening" | Lynis hardening index (latest, 15 d), Lynis warnings (last 8 d) |

## AI inventory (`uid ai-inventory`)

Cisco AIBOM results from Loki: components per host (latest run), new and removed components in the last 24 h, latest
runs (counts per type and target, errors), plus the DefenseClaw AIBOM (Jetson, `homelab-aibom`) and two MCP drift
panels ("MCP drift findings, last 2 days" and "MCP drift (Jetson, mcp-drift)", from journal tag `mcp-drift`).

## Model API callers (`uid model-api-callers`)

Who called LiteLLM. From `litellm-usage-exporter` on dgx-1 (VictoriaMetrics, `litellm_usage_*`): requests and failed
share in the last 24 h, tokens, whether the exporter reads the DB; calls per key alias per minute, error rate by key,
latency p50/p95 by model (successful requests), top callers of the last 24 h (alias, hash8, calls, tokens, errors),
calls per key and source host. From the front door's access log (Loki, `model.nghodki.ai` `/v1/`): calls by source
node over time and requests per `api_key_hash` and node, next to the hash8 → alias table. Source nodes: `10.42.1.x`
dgx-1, `10.42.0.x` dgx-2, `10.42.2.x` Jetson, `10.42.3.x` Dell. See [LiteLLM](../services/litellm.md).

## Argo CD (`uid argocd`)

The upstream Argo CD dashboard: app health and sync, sync activity and failures, controller reconciliation, repo-server
Git requests, server API requests, redis. Fed by the fixed-ClusterIP scrapes.

## DefenseClaw (19, vendored from the 1.0.9 release)

Overview · Agent Activity (Live) · Agent identity · Identity & Users · Agent360 · Blocked Events & Analysis ·
AI Agent Usage & Detection · AI Discovery Runtime Planes · Hook Connectors · Connector Detail · Guardrail Evaluations ·
Policy decisions · HITL · Findings (Rule detail) · Scanners (Ops) · Proxy & LLM Guard · Sandboxes ·
Runtime & Reliability · IoT Fleet (`/d/defenseclaw-fleet`).

They are copied **unchanged** (`dashboards/defenseclaw/SOURCE.md`); CI (`defenseclaw-bundle.py check`) fails if they
differ from the pinned release. Don't edit them; on a DefenseClaw upgrade run `defenseclaw-bundle.py sync`.

## Data sources (`provisioning/datasources/datasources.yml`)

UIDs kept from DefenseClaw so its dashboards work unchanged:

| Name | UID | URL |
|---|---|---|
| Prometheus (VictoriaMetrics), default | `defenseclaw-prometheus` | `http://victoriametrics:8428` |
| Loki | `defenseclaw-loki` | `http://loki:3100`; derived field `trace_id` → Tempo |
| Tempo | `defenseclaw-tempo` | `http://tempo:3200`; traces to logs, metrics, service map |
| Alertmanager | `defenseclaw-prometheus-alerts` | `http://alertmanager:9093` |

## Useful Loki queries

```logql
{host_name="nikghodki-raspberry"} |= "INTERVENTION"         # safety governor interventions
{host_name=~".+"} |= "hardening_index="                      # Lynis summaries, all hosts
{host_name="spark-83dc"} |= "cisco-aibom"                       # Cisco AIBOM runs on dgx-1
{host_name="nikghodki-raspberry"} |= "INTERVENTION" | json ident="SYSLOG_IDENTIFIER", msg="MESSAGE" | ident="safety-governor" | line_format "{{.msg}}"
```

`host_name` is the OS hostname (`spark-83dc`, `nikghodki-dgx-2`, `nikhil-jetson`, `nikghodki-omarchy-local`,
`nikghodki-raspberry`) and is a stream label. The journal identifier is a field in the JSON body, not a label. The last
query is the tested one from runbooks/robot-safety.md; the others are examples (unverified).

## Add or change a dashboard

1. Build it in Grafana (a scratch copy), export JSON, save it under `dashboards/fleet/` or `cluster/`.
2. Use the data source UIDs above.
3. PR, merge, `playbooks/observe.yml`. Grafana picks up files on restart of the `grafana` service (the role restarts
   it when the folder changed).
