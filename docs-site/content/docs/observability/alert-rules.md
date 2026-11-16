---
title: Alert rules
description: Every vmalert rule group and alert, what its expression means, its severity and where it goes.
---

Rules are files in `hosts/stacks/observe/vmalert/rules/`, evaluated every 30 s by vmalert on dgx-2. All alerts go to
Alertmanager, then to ntfy (see [Alert delivery](alert-delivery.md) for routing). Severity `critical` repeats every 30 min;
others every 4 h.

## Fleet (`fleet.yml`)

| Alert | Group | Means | For | Severity |
|---|---|---|---|---|
| `FleetHostSilent` | fleet-hosts | `max by (host_name) (lag(system_memory_usage_bytes{state="used"}[1d])) > 300`: a host's last sample is over 5 min old (its collector or the host is down). `lag()` over a day since #74 (the old instant selector dropped a silent host before 300 s, so it never fired); resolves after a day of silence, when the Gatus ssh checks still cover it | 2m | critical |
| `FleetDiskWarning` | fleet-hosts | a filesystem is over 80% used | 10m | warning |
| `FleetDiskCritical` | fleet-hosts | over 90% used | 5m | critical |
| `FleetMemoryLow` | fleet-hosts | free + cached memory under 2 GB | 10m | warning |
| `FleetGpuHot` | fleet-thermal | DCGM GPU temperature over 85 °C | 10m | warning |
| `FleetHostHot` | fleet-thermal | hottest fleet-metrics sensor over 85 °C | 10m | warning |
| `FleetPiHot` | fleet-thermal | Pi over 78 °C (it throttles from 80) | 5m | warning |
| `FleetGpuMetricsMissing` | fleet-thermal | a Spark reports fleet-metrics GPU but no DCGM (gpu stack down?) | 15m | warning |
| `ObservabilityComponentDown` | fleet-stack | any scrape target `up == 0` | 5m | warning |

## Alerting host (`alerting-host.yml`)

| Alert | Means | For | Severity | Route |
|---|---|---|---|---|
| `AlertingHostDown` | `max(up{job="gatus"}) < 1 or absent(...)`: dgx-2 can't scrape the Dell's Gatus (Dell, Docker, status-proxy or Gatus down, or dgx-2 can't reach it) | 15m | critical | ntfy.sh backup topic, fixed text "alerting host unreachable" |
| `AlertDeliveryFailing` | Alertmanager's webhook notifications kept failing for 15 min (e.g. the Dell's ntfy broken while Gatus answers) | 15m | critical | ntfy.sh backup topic, "alert delivery failing"; inhibited while `AlertingHostDown` fires |

Labels and annotations here carry no hostnames or addresses (`max()` drops `instance`), because the webhook body goes
to the public ntfy.sh.

## Watchdog (`watchdog.yml`)

| Alert | Means | Route |
|---|---|---|
| `Watchdog` | `vector(1)`: always firing, severity `none` | Gatus external endpoint on the Dell every 5 min. Gatus alerts when it stops for 15 min |

## Edge Connector (`edge.yml`)

| Alert | Means | For | Severity |
|---|---|---|---|
| `EdgeDeviceOffline` | Fleet reports at least one device offline | 10m | warning |
| `EdgeCanaryRollback` | `defenseclaw_fleet_policy_rollback_total` went up in 15 min | — | warning |
| `EdgeOtaRollback` | `defenseclaw_fleet_ota_rollbacks_total` went up | — | warning |

## k3s (`k3s.yml`), from Gatus results

| Alert | Means | For | Severity |
|---|---|---|---|
| `K3sEtcdMemberDown` | fewer than 3 of the Gatus "etcd …" TCP checks succeed | 5m | warning |
| `K3sEtcdQuorumLost` | fewer than 2 succeed: the API is read-only or down | 2m | critical |
| `K3sApiDown` | neither "API dgx-1" nor "API dgx-2" answers | 3m | critical |

These depend on Gatus (Dell) **and** VictoriaMetrics/vmalert (dgx-2).

## GitOps (`gitops.yml`)

| Alert | Means | For | Severity |
|---|---|---|---|
| `ArgoCDAppOutOfSync` | an app hasn't matched Git | 15m | warning |
| `ArgoCDAppNotHealthy` | an app isn't Healthy | 15m | warning |
| `ArgoCDMetricsDown` | the application controller's metrics don't answer (nothing syncs; app alerts are blind) | 10m | warning |
| `KyvernoAdmissionDown` | no admission replica answers: new pods in enforced namespaces are **refused** (kube-system, kyverno, argocd keep working) | 5m | critical |
| `KyvernoAdmissionDegraded` | fewer than 2 admission replicas available (from kube-state-metrics, P3.3) | 15m | warning |
| `KyvernoRejectionsSpike` | more than 5 refusals in 15 min (seen by one replica) | — | warning |
| `KyvernoWebhookErrors` | the admission webhook answers 5xx (those requests are refused) | 10m | warning |
| `KyvernoAdmissionSlow` | admission p99 above 8 s (webhook timeouts are 10 s, 20 s for `verify-images`) | 15m | warning |

## Front door (`front-door.yml`)

The front door in k3s (P3.3), from kube-state-metrics at 10.43.0.120. `KubeVipDown` and `EdgeFrontDoorDown` are
critical since the cutover (#79). Gatus group `edge` checks the VIPs themselves.

| Alert | Means | For | Severity |
|---|---|---|---|
| `KubeVipNotReady` | the kube-vip DaemonSet isn't ready on every Spark (the VIPs can't fail over) | 5m | warning |
| `KubeVipDown` | no kube-vip ready: 192.168.86.10/.11 may be on no node | 1m | critical |
| `EdgeReplicasDown` | an `edge` Deployment (edge-caddy, edge-dns) has fewer than 2 ready replicas | 10m | warning |
| `EdgeFrontDoorDown` | an `edge` Deployment has no ready replica: `*.nghodki.ai` DNS or HTTPS is down | 2m | critical |
| `KubeStateMetricsDown` | kube-state-metrics doesn't answer (the rules above are blind) | 10m | warning |

## Robot (`robot.yml`)

| Alert | Means | For | Severity |
|---|---|---|---|
| `SafetyGovernorStatusStale` | the governor hasn't published status for 60 s, or no metric for 3 min (dead or hung) | 2m | critical |
| `SafetyGovernorLidarStale` | no `/scan` for over 5 s (ros-lidar or the Zenoh router down?) | 5m | warning |
| `SafetyGovernorRealSinkEnabled` | a real motor sink has been on for 2 h (left on after a test) | 2h | warning |

## DefenseClaw (vendored, `defenseclaw-alerts.yml`, `defenseclaw-recording.yml`)

Copied unchanged from the 1.0.9 release (30 alerts, 31 recording rules). Groups and alerts:

| Group | Alerts (severity) |
|---|---|
| `defenseclaw.correctness` | SchemaViolations (critical), GatewayErrorsSpike (warning), Panic (critical) |
| `defenseclaw.slo.alerts` | BlockSLOBreach (critical) |
| `defenseclaw.pipeline` | OTLPExporterStalled (critical), OTLPExporterErrors (warning), AuditSinkFailures (critical), AuditSinkCircuitOpen (warning) |
| `defenseclaw.security` | ManagedAIDFailOpenSustained (critical), BlockRateSpike, SandboxEgressBlocksSustained, SandboxErrorsSustained, JudgeErrorRate, WebhookFailuresSustained (warning) |
| `defenseclaw.traffic` | HTTP5xxSpike, HTTPAuthFailuresSurge, RateLimitSurge (warning) |
| `defenseclaw.runtime` | GoroutineLeak, SQLiteBusyRetries, ConfigLoadErrors (warning) |
| `defenseclaw.connectors` | ConnectorTelemetrySilent, ConnectorTelemetryMalformed (warning) |
| `defenseclaw.observability_pipeline` | LokiIngestOverflow (warning) |
| `defenseclaw.ai_discovery` | AIDiscoveryStalled, AIDiscoveryDetectorErrors (warning) |
| `defenseclaw.kernel` | KernelDenials (info), KernelAckStale (warning), KernelPausedLong (info), TetragonFallback (warning), CustomerPolicyBlocksAgents (info) |

All names start with `DefenseClaw`. Recording groups: guardrail, http, scanner, slo.recording, sinks, exporters,
observability_pipeline, connectors.

## Add a rule

1. Add it to the right file (or a new `*.yml`) in `hosts/stacks/observe/vmalert/rules/`. Never edit the
   `defenseclaw-*.yml` files.
2. Keep labels `severity: critical|warning|info`. Use `host_name` or `fleet_host` so Alertmanager groups per host.
3. PR (yamllint checks it), merge, `playbooks/observe.yml`.
4. Test the route: `docker exec observe-alertmanager-1 amtool --alertmanager.url=http://127.0.0.1:9093 config routes test alertname=<name> severity=<sev>`.

Not built yet: the architecture's "DefenseClaw gateway down" alert per host via Gatus (gateways listen on loopback, so
Gatus on the Dell can't check them; DefenseClaw's own `ConnectorTelemetrySilent` is the closest).
