---
title: "Jetson"
description: "The Jetson Orin: Hermes (two profiles), Home Assistant, the Zenoh router, LiveKit and the control center (voice and vision retired, D26); an etcd member and tainted k3s worker."
---

The Jetson is the home and robot brain. It also holds the third etcd vote, which is what keeps the k3s API writable
when one Spark is down. Its memory is tight; treat every new process here as a budget decision.

## Hardware and OS

| | |
|---|---|
| Hostname | `nikhil-jetson` |
| Hardware | Jetson Orin, 6 cores, 7.4 GiB, 3.6 TB NVMe (4% used) |
| OS | JetPack 7.2.1 (L4T R39.2.1), Ubuntu 24.04.4, kernel 6.8.12-1021-tegra. Reflashed 2026-11-12 (the old JetPack 6 Humble install is gone) |
| LAN | `wlP1p1s0` 192.168.86.211 (Wi-Fi) |
| Tailscale | 100.78.145.123, `nikhil-jetson.tail1cb707.ts.net`, `tag:control`, `tag:home`, `tag:agent` |
| Users | `nikjetson` (uid 1000, admin, the main Hermes profile), `hermes-nikhil` (uid 2002, linger on, the second Hermes profile) |

## What runs here

### As `nikjetson` (systemd user units)

| Unit | What | Listens |
|---|---|---|
| `hermes-gateway` | Hermes main profile (`~/.hermes/hermes-agent`), platform `api_server` | 0.0.0.0:8642 |
| `defenseclaw-gateway` | DefenseClaw 1.0.9 for nikjetson | 127.0.0.1:18970 |
| `livekit-server` | LiveKit 1.13.5 (`/opt/livekit/1.13.5`, `--config ~/.config/livekit/livekit.yaml`, no `--dev`; role `livekit`, `playbooks/home.yml`), used by the control center after voice was retired (D26) | 127.0.0.1:7880 |
| `control-center` | RoboClaw Control Center (uvicorn, py310 venv) | 0.0.0.0:8200 |
| `vision-service` | RoboClaw vision service (face recognition, presence) | **disabled and inactive** since D26 (2026-11-15) |
| `homelab-aibom.timer` | DefenseClaw AIBOM, 03:15 | — |
| `mcp-drift.timer` | MCP drift check, ~03:40 (also for hermes-nikhil) | — |

`hermes-gateway-nikhil-ghodki` (the old second-profile unit under nikjetson) is disabled but kept for rollback.

### As `hermes-nikhil`

| Unit | What | Listens |
|---|---|---|
| `hermes-gateway` | Hermes profile nikhil-ghodki (own checkout of the same commit). Platforms: Slack, Home Assistant, api_server | 100.78.145.123:8643 (Tailscale only) |
| `defenseclaw-gateway` | DefenseClaw 1.0.9 for hermes-nikhil (`gateway.port` 18971) | 127.0.0.1:18980 |

### System

| Unit / container | What | Listens |
|---|---|---|
| container `homeassistant` | `ghcr.io/home-assistant/home-assistant:2026.11.1` pinned by digest, host network; stack `hosts/stacks/home-assistant` (`playbooks/home.yml`) | 0.0.0.0:8123 |
| `ros-zenoh-router.service` | container `ros-zenoh-router`, image `homelab/ros-zenoh:kilted-1`, host network | *:7447 |
| `k3s.service` | etcd-only server + kubelet (`disable-apiserver` etc.) | 192.168.86.211:2379, *:10250, *:6443 (k3s supervisor, not a full API server) |
| `otelcol-contrib`, `fleet-metrics`, `tailscaled`, `docker` | standard | 9109 |
| `nvidia-cdi-refresh` drop-in | CSV mode and retry (role `jetson_cdi`) | — |
| container `backup-rest-server-1` | the fleet's restic rest-server (decision 0002, [Backup server](../services/backup-server.md)): host network, 256m; repositories on the 500 GB `/srv/homelab-backup` (loop image `/var/lib/homelab-backup.img`); `backup-server-guard.service` lets only fleet hosts in | *:8000 (TLS, fleet LAN sources only) |

Timers: `cisco-aibom.timer` at 01:30 (code dirs only, 3 h per target, each Hermes checkout is about 8,000 Python files; this host's images are scanned on dgx-2 by digest), `lynis-audit`,
`homelab-backup`, `homelab-backup-prune` (daily 05:30, 3 days kept, every host's repository).

## Memory

About 3.4 GiB available with two Hermes profiles, Home Assistant, LiveKit, Zenoh and DefenseClaw. k3s and containerd
take about 430 MB. Kubelet: `system-reserved=cpu=1500m,memory=4Gi`, `kube-reserved=cpu=500m,memory=768Mi`,
`eviction-hard=memory.available<300Mi`, `max-pods=40`, so about 2.3 GiB allocatable for pods. Ansible refuses a first
k3s install with less than 2048 MiB available (`k3s_min_mem_available_mb`).

## Operate

```bash
ssh -p 2245 nikjetson@localhost                  # from the admin laptop
systemctl --user status hermes-gateway defenseclaw-gateway
sudo -u hermes-nikhil XDG_RUNTIME_DIR=/run/user/2002 systemctl --user status hermes-gateway
ros2-kilted topic hz /scan                       # ROS CLI inside the router container
```

## Gotchas

- `/usr/bin/node` is gone since the JetPack 7 reflash. The second profile's MCP server uses Hermes' bundled Node.
- Hermes' main profile `api_server` listens on all interfaces (0.0.0.0:8642), so it is reachable on the LAN.
- The Jetson is on Wi-Fi and is an etcd member. A Wi-Fi drop takes it out of quorum until it reconnects (decision 0005).
- `ros2-kilted` only works while the router container runs.
- The tegra kernel has no iptables `NFLOG` target and no `physdev` match (not even as modules). k3s's network policy
  controller needs both, so k3s here runs `iptables-restore` through a wrapper that drops those rules
  (`k3s_netpol_iptables_shim`, [k3s runbook](https://github.com/nikghodki/homelab/blob/main/runbooks/k3s.md#known-issues)). Without it, NetworkPolicies are not
  enforced on this node.
