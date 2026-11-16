---
title: Docs vs live state
description: Every difference found on 2026-11-15 between the repo's docs and the live hosts, or between documents. Nothing outside docs-site was changed.
---

Found while writing these pages, by reading the repo at `main` and checking hosts read-only. None of these were fixed
here; each needs a decision or a PR in its own area. Rows are removed when fixed; the numbers of the others are kept.
Fixed since: #2 and #5 (vision service running, broken voice route: both retired by D26, #75, #76) and #9 (the P3.3
apps ran from a branch: merged in #72). Fixed 2026-11-15/16: #3 (#90), #4 and #12 (#89), and the document rows #13–#19, #21–#23
and #26 (the 2026-11-16 status PR).

## Live state differs from a decision or the docs

| # | What the repo says | What is live | Where to look |
|---|---|---|---|
| 1 | Decision 0002: backups "stay merged but **not deployed**" | The restic rest-server runs on dgx-2; `homelab-backup.timer` is enabled on dgx-1, dgx-2, the Jetson and the Pi; `homelab-backup-prune.timer` on dgx-2; dgx-1's run at 03:24 on 2026-11-15 saved a snapshot. Not installed on the Dell | [Backups](../operations/backups.md) |
| 6 | (not in the repo) | `earlyoom` and `gpu-oom-guard.service` run on both Sparks; the unit file says "Managed by homelab Ansible (roles/memory_guard)", but no `memory_guard` role exists on `main` or any remote branch | [GPU OOM incident](../operations/incident-gpu-oom.md) |
| 7 | Architecture §3.1: Fleet broker, NATS, LiteLLM "in k3s" | They run in Docker; only Argo CD, Kyverno, CNPG, CoreDNS zone and P3.3's kube-vip, `edge` front door and kube-state-metrics are in k3s | [Platform](../platform/index.md) |
| 8 | Decision 0008: GHCR packages `mlflow` and `ros-zenoh` public | Still private: Kyverno refuses both with `UNAUTHORIZED` (P3.5 acceptance case b pending) | [Kyverno](../platform/kyverno.md) |
| 10 | Design §4.2 / architecture §4.3: no service open to the LAN unless needed | LiteLLM :4000, Open WebUI :3100, Grafana :3000, Phoenix :6006, OTLP 4317–4320, Hermes :8642, control center :8200, fleet-metrics :9109 listen on all interfaces; Temporal and Zenoh have no auth | [Ports](../network/ports.md) |
| 11 | "Pin everything" (cluster/README, CI rules) | Home Assistant is pinned by digest in `hosts/stacks/home-assistant` (#85); the edge-gateway containers (`caddy:2.11`, `nginx:alpine`, dnsmasq) are stopped since #92 (kept as the rollback, platform session); `dgxmm:latest` is the DGXMM session's | [Upgrades](../operations/upgrades.md) |

## Documents that are behind or inconsistent

| # | Document | Says | Should say |
|---|---|---|---|
| 20 | `policies/defenseclaw/homelab.yaml` comment | LiteLLM gateway "(D18)" | D20. Left for the next real policy change: any edit to the file re-activates the policy (gateway reload) on every host |
| 24 | `docs/architecture.md` §3, §11 | SeaweedFS, CrowdSec, Tetragon, ARC runner, Gatus/ntfy on dgx-2 | not deployed (SeaweedFS, CrowdSec, Tetragon, ARC) or moved (Gatus/ntfy → Dell) |
| 25 | `agents/hermes/card.yaml` | `url: https://hermes.nghodki.ai/a2a` | placeholder; no DNS record |

## Not checked

- The laptop-side SSH tunnels (ports 2244, 2245, 2248).
- The Tailscale admin console (split DNS, the applied policy matches the file).
- LiteLLM's routes and image digest, DGXMM internals (owned by the DGXMM session).
- Certificate expiry dates for `nats.crt`, `fleet.crt`, `backup.crt`.
