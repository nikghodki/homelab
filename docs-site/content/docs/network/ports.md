---
title: Ports
description: Every port that matters, per host, with what binds it and who may reach it.
---

"Bind" is the address the socket listens on. "LAN" means 192.168.86.0/24; "tailnet" means it is also reachable over
Tailscale if the [policy](tailscale.md) grants it. Checked with `ss -tln` and `docker ps` on 2026-11-15 (LiteLLM and
Pocket ID rows: 2026-11-16, after their move into k3s).

## dgx-1 (192.168.86.44, 100.65.137.82)

| Port | Bind | Service | Notes |
|---|---|---|---|
| 22 | all | sshd | |
| 53 | 100.65.137.82 | edge-dns (k3s, kube-proxy DNAT) | edge-dnsmasq on 192.168.86.44 stopped 2026-11-15 |
| 80, 443 | 100.65.137.82 | edge-caddy (k3s, kube-proxy DNAT) | the old edge-caddy on 0.0.0.0 stopped 2026-11-15 |
| 3100 | all | Open WebUI (Docker): **stopped** since the move into k3s (2026-11-16); only `webui.nghodki.ai` now | |
| 4000 | 127.0.0.1, 10.100.136.1 | transition relays → LiteLLM in k3s (10.43.0.150:4000) | until 2026-11-23. LiteLLM itself listened on all interfaces until it moved into k3s (2026-11-16); use `model.nghodki.ai` |
| 8091 | 10.100.136.1 | relay → DGXMM's on-demand gateway, for the LiteLLM pods | |
| 4222 | all | NATS (TLS, homelab CA) | |
| 8883 | all | NATS MQTT (TLS) | picoclaw |
| 8222 | 127.0.0.1 | NATS monitoring | |
| 8884 | all | Fleet Mosquitto (TLS, MQTT 5) | Edge Connector devices, the Fleet gateway |
| 8971 | all (host network) | fleet-caddy, Fleet API TLS proxy | forwards only `/api/v1/fleet/*` |
| 18970 | 127.0.0.1; 10.100.136.1 (relay) | DefenseClaw gateway API (incl. Fleet); the relay `litellm-defenseclaw-cable` for the LiteLLM pods | |
| 5432, 6379 | 127.0.0.1 | LiteLLM Postgres, Redis (Docker): **stopped** since the move into k3s (2026-11-16) | |
| 8090 | 127.0.0.1 | DGXMM | via `dgxmanager.nghodki.ai` |
| 9109 | all | fleet-metrics | |
| 9400 | 127.0.0.1 | dcgm-exporter | |
| 6443, 10250 | all | k3s API, kubelet | |
| 2379, 2380 | 10.100.136.1, 127.0.0.1 | etcd | |
| 2049, 111, 5201 | — | NFS server, rpcbind, iperf3 | stopped and disabled 2026-11-15 (role `retired_units`) |

## dgx-2 (192.168.86.36, 100.124.175.23)

| Port | Bind | Service |
|---|---|---|
| 3000 | all | Grafana |
| 6006 | all | Phoenix (UI and OTLP HTTP `/v1/traces`) |
| 4317, 4318 | all | otel-defenseclaw (OTLP gRPC/HTTP) |
| 4319, 4320 | all | otel-fleet (OTLP gRPC/HTTP), host collectors push here |
| 1411 | 192.168.86.36 | Pocket ID (Docker): **stopped** since the move into k3s (2026-11-16); only `id.nghodki.ai` now |
| 7233 | 192.168.86.36 | Temporal frontend gRPC (mTLS required) |
| 8233 | 192.168.86.36 | Temporal Web UI |
| 9233 | 192.168.86.36 | Temporal Prometheus metrics |
| 4181 | 192.168.86.36 | MLflow UI gate (the `api` Caddy; front door token, else 403) |
| 5000 | 192.168.86.36 | MLflow job API (Caddy, basic auth) |
| 8000 | all (Jetson; nftables lets only fleet LAN addresses in) | restic rest-server (TLS) |
| 9400 | 127.0.0.1 | dcgm-exporter |
| 9109 | all | fleet-metrics |
| 6443, 10250, 2379 | as dgx-1 | k3s |

Not published (stack network only): VictoriaMetrics 8428, vmalert 8880, Alertmanager 9093, Loki 3100, Tempo 3200,
the Postgres instances, MLflow 5000 inside the stack.

## Jetson (192.168.86.211, 100.78.145.123)

| Port | Bind | Service |
|---|---|---|
| 8123 | all | Home Assistant (host network) |
| 8642 | all | Hermes api_server, main profile |
| 8643 | 100.78.145.123 | Hermes api_server, hermes-nikhil |
| 8200 | all | RoboClaw control center |
| 7447 | all | Zenoh router |
| 7880 | 127.0.0.1, ::1 | LiveKit |
| 18970 | 127.0.0.1 | DefenseClaw gateway (nikjetson) |
| 18980 | 127.0.0.1 | DefenseClaw gateway (hermes-nikhil) |
| 2379 | 192.168.86.211, 127.0.0.1 | etcd member |
| 6443, 10250 | all | k3s supervisor, kubelet |
| 9109 | all | fleet-metrics |

## Dell (192.168.86.49, 100.117.118.69)

| Port | Bind | Service |
|---|---|---|
| 8081 | 192.168.86.49 | status-gate (Caddy) → Gatus: UI with the front door token only; `/health`, `/metrics`, heartbeat open |
| 8082 | 127.0.0.1 | Gatus itself (break-glass via SSH tunnel) |
| 8085 | 127.0.0.1, 192.168.86.49 | ntfy |
| 443 (tailnet) | tailscaled | `tailscale serve` → 127.0.0.1:8085 |
| 4180 | 192.168.86.49 | ops stack Caddy → Homepage (front door token, else 403) |
| 4181 | 192.168.86.49 | ops stack Caddy → docs site (front door token, else 403; `/healthz` open) |
| 10250 | all | kubelet |
| 9109 | all | fleet-metrics |

## Pi (192.168.86.39, 100.64.25.22)

| Port | Bind | Service |
|---|---|---|
| 22 | all | sshd |
| 9109 | all | fleet-metrics |
| 9113 | 127.0.0.1 | safety governor metrics |
| 18790 | 127.0.0.1 | local picoclaw/agent port (unverified) |

Outbound from the Pi: MQTT 8883 and NATS 4222 to dgx-1 (picoclaw, governor), Fleet MQTT 8884 to dgx-1 (Edge
Connector), Zenoh 7447 to the Jetson, OTLP 4319 to dgx-2.
