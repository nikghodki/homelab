---
title: "dgx-1"
description: "The first DGX Spark: interactive models, a front-door replica and the nginx-gateway relay, NATS, DefenseClaw Fleet, Ansible control node, k3s server."
---

dgx-1 is the busiest host. It serves the interactive models and runs one of the two front-door replicas. It is also
where people and agents work: the repo clone, the age key, Ansible and kubectl all live here. Since the P3.3 cutover
(2026-11-15) the web front door and DNS run in k3s on both Sparks
([Front door](../network/front-door.md#in-cluster-front-door-p33)), but the routes behind nginx-gateway (model,
dgxmanager, ha), LiteLLM, NATS and Fleet still go down with dgx-1 (see
[Failure scenarios](../observability/failure-scenarios.md)).

## Hardware and OS

| | |
|---|---|
| Hostname | `spark-83dc` |
| Hardware | NVIDIA DGX Spark, GB10 (Grace Blackwell), 20 cores, 121 GiB unified memory, 3.7 TB NVMe (32% used) |
| OS | Ubuntu 24.04.5 LTS (DGX OS), kernel 7.0.0-1025-nvidia, NVIDIA driver 580.178 (architecture §10.1) |
| User | `nikghodki-dgx` |
| LAN | `wlP9s9` 192.168.86.44 (Wi-Fi). Also carries the kube-vip VIPs 192.168.86.10 (k3s API) and .11 (edge) as /32s while dgx-1 holds their leases (both at check time; they move to dgx-2 on failover; [Cluster networking](../network/cluster-network.md#addresses-outside-the-cluster-p33)) |
| Tailscale | 100.65.137.82, `spark-83dc.tail1cb707.ts.net`, `tag:gpu`, `tag:control` |
| Spark cable 1 | `enp1s0f0np0` 10.100.136.1/24 (k3s, etcd, flannel) |
| Spark cable 2 | `enP2p1s0f0np0` 10.100.137.1/24 (RDMA/NCCL for pooled models) |
| 10 GbE | `enP7s7`, down (P0.11) |

## What runs here

### Docker containers

| Container | Image | Published | Managed by |
|---|---|---|---|
| `edge-caddy` | `caddy:2.11` (tag, not a digest) | 0.0.0.0:80, :443 (reached on 192.168.86.44: the nginx-gateway relay and the rollback since the P3.3 cutover) | hand, `~/edge-gateway` |
| `edge-dnsmasq` | `edge-dnsmasq:local` (Alpine 3.20 + dnsmasq) | host network, :53 on 192.168.86.44 and 100.65.137.82 (the latter is DNATed to the cluster since the cutover; kept for the rollback) | hand, `~/edge-gateway` |
| `nginx-gateway` | `nginx:alpine` | none (Docker network `gateway`) | hand, `~/voice-assistant/nginx` |
| `litellm-proxy` | `ghcr.io/berriai/litellm:v1.109.1` (digest-pinned, P0.13) | 0.0.0.0:4000 | hand, `~/litellm-setup` |
| `litellm-postgres` | `postgres:16-alpine` | 127.0.0.1:5432 | hand |
| `litellm-redis` | `redis:7-alpine` | 127.0.0.1:6379 | hand |
| `open-webui` | `ghcr.io/open-webui/open-webui:v0.13.3` | 0.0.0.0:3100 | hand |
| `dgxmm` | `dgxmm:latest` | 127.0.0.1:8090 | DGXMM project |
| `coolify`, `coolify-db`, `coolify-redis`, `coolify-sentinel` | `coollabsio/coolify:4.7.3` and friends | 0.0.0.0:8000, :6001, :6002 | Coolify |
| `bus-nats-1` | `nats:2.15.3-alpine` | 0.0.0.0:4222, :8883; 127.0.0.1:8222 | `playbooks/bus.yml` |
| `fleet-mosquitto-1` | `eclipse-mosquitto:2.1.2-alpine` | 0.0.0.0:8884 | `playbooks/fleet.yml` |
| `fleet-caddy-1` | `caddy:2.11.9-alpine` | host network, :8971 | `playbooks/fleet.yml` |
| `gpu-dcgm-exporter-1` | `nvcr.io/nvidia/k8s/dcgm-exporter:4.4.2-4.7.1` | 127.0.0.1:9400 | `playbooks/gpu.yml` |

DGXMM starts model engines (vLLM, llama.cpp) as more containers when models load; none were loaded at check time.

### systemd

| Unit | What |
|---|---|
| `k3s.service` | k3s server + etcd (node IP 10.100.136.1) |
| `otelcol-contrib.service` | host collector; also scrapes dcgm-exporter and the Fleet API metrics |
| `fleet-metrics.service` | `:9109` |
| `tailscaled.service` | Tailscale |
| `earlyoom.service`, `gpu-oom-guard.service` | Memory guards added after the 2026-11-15 OOM. The unit says "Managed by homelab Ansible (roles/memory_guard)", but no such role exists in the repo on any branch (unverified who installed it; likely the DGXMM session) |
| `nvidia-persistenced`, `dgx-dashboard`, `dgx-dashboard-admin` | DGX OS |
| NFS server (`nfs-mountd`, `nfsdcld`, ...), `iperf3` | Present and running; not documented in the repo (purpose unverified) |
| user `defenseclaw-gateway.service` | DefenseClaw 1.0.9 gateway with the Fleet gateway, API on 127.0.0.1:18970 |

Timers: `cisco-aibom.timer` (~04:20), `lynis-audit.timer` (Sunday ~03:30), `homelab-backup.timer` (02:30; see
[Backups](../operations/backups.md)), and the distro's own `lynis.timer`.

### k3s pods

Argo CD controller and redis, CNPG operator, Kyverno admission and reports controllers, kube-state-metrics (where the
scheduler put them; any Spark is fine); one replica each of `edge/edge-caddy` and `edge/edge-dns` and a kube-vip pod
(one per Spark). See [k3s](../platform/k3s.md).

## Files that matter

| Path | What |
|---|---|
| `~/homelab` | The repo clone (`main`). Use a worktree under `~/homelab-wt/` for your own branch. |
| `~/.config/sops/age/keys.txt` | The fleet age private key (0600). See [SOPS and age](../security/secrets.md). |
| `~/.venvs/ansible` | Ansible venv. Run playbooks from `~/homelab/hosts`. |
| `~/.kube/config` | Admin kubeconfig (server `https://192.168.86.44:6443`), not in Git |
| `~/.local/bin` | `gh` (as nikghodki), `sops`, `helm`, `argocd`, `cosign`, `safety-reset`, `safety-estop` |
| `~/edge-gateway/conf/Caddyfile`, `~/edge-gateway/dnsmasq/dnsmasq.conf` | The old front door and DNS (outside the repo): nginx-gateway relay and rollback. Routes live in `cluster/platform/edge/` since the P3.3 cutover (`runbooks/edge.md`) |
| `~/.defenseclaw/` | DefenseClaw config, `.env` (Fleet secrets), audit DB |
| `/opt/homelab/bus`, `/opt/homelab/fleet`, `/opt/homelab/gpu` | Deployed stacks |
| `/etc/safety-operator/nats-operator.json` | NATS `operator` credentials for `safety-reset` (root, 0600) |

## Operate

- Shell setup: `export PATH=$HOME/.local/bin:$PATH KUBECONFIG=$HOME/.kube/config`.
- Health: `docker ps`, `curl -s http://127.0.0.1:4000/health/liveliness` (LiteLLM), `kubectl get nodes`.
- Restart edge-caddy after a config change: `docker restart edge-caddy` (a `caddy reload` hasn't always taken
  effect). The in-cluster front door: `kubectl -n edge rollout restart deploy/edge-caddy`.

## Gotchas

- dgx-1's umask is 002. uv's Python tree inherits it, and the DefenseClaw policy compiler refuses a group-writable
  interpreter (see [Troubleshooting](../operations/troubleshooting.md)).
- Its LAN link is Wi-Fi. After a reboot, containers that publish on a LAN IP can fail if Wi-Fi comes up late.
- LiteLLM (:4000), Open WebUI (:3100) and Coolify (:8000) listen on all interfaces, so they are reachable on the LAN
  directly, not only through the front door.
