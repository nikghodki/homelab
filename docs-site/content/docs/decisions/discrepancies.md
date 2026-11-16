---
title: Docs vs live state
description: Every difference found on 2026-11-15 between the repo's docs and the live hosts, or between documents. Nothing outside docs-site was changed.
---

Found while writing these pages, by reading the repo at `main` and checking hosts read-only. None of these were fixed
here; each needs a decision or a PR in its own area.

## Live state differs from a decision or the docs

| # | What the repo says | What is live | Where to look |
|---|---|---|---|
| 1 | Decision 0002: backups "stay merged but **not deployed**" | The restic rest-server runs on dgx-2; `homelab-backup.timer` is enabled on dgx-1, dgx-2, the Jetson and the Pi; `homelab-backup-prune.timer` on dgx-2; dgx-1's run at 03:24 on 2026-11-15 saved a snapshot. Not installed on the Dell | [Backups](../operations/backups.md) |
| 2 | D19: vision is not deployed | `vision-service.service` (RoboClaw face recognition + presence, `:8090`) is enabled and running as a nikjetson user unit on the Jetson (port not seen listening) | [Jetson](../hosts/jetson.md) |
| 3 | P0.9 ✅ "fix `pi.nghodki.ai`" | edge-dnsmasq still answers `pi.nghodki.ai` and `raspberrypi.nghodki.ai` with 192.168.86.34; the Pi is .39 | [DNS](../network/dns.md) |
| 4 | P1.12: "retire the SSH tunnel to the Jetson" | `dclaw-tunnel` (ssh `-L 18970` to the Jetson's Tailscale IP) is still enabled on the Pi; nothing was listening on the Pi's 18970, and the Tailscale policy has no `tag:robot` → Jetson:22 grant, so it is probably failing in a loop (unverified) | [Pi](../hosts/pi.md) |
| 5 | `voice-agent.nghodki.ai` LiveKit route → `100.65.137.82:7880` (dgx-1) | Nothing listens on dgx-1:7880; LiveKit runs on the Jetson on 127.0.0.1:7880. `/rtc` returned 502. The voice page's `/token` upstream (`host.docker.internal:7890`) and `kokoro-tts` weren't running either | [Voice](../services/voice.md) |
| 6 | (not in the repo) | `earlyoom` and `gpu-oom-guard.service` run on both Sparks; the unit file says "Managed by homelab Ansible (roles/memory_guard)", but no `memory_guard` role exists on `main` or any remote branch | [GPU OOM incident](../operations/incident-gpu-oom.md) |
| 7 | Architecture §3.1: Fleet broker, NATS, LiteLLM "in k3s" | They run in Docker; only Argo CD, Kyverno, CNPG, CoreDNS zone (and P3.3's test apps) are in k3s | [Platform](../platform/index.md) |
| 8 | Decision 0008: GHCR packages `mlflow` and `ros-zenoh` public | Still private: Kyverno refuses both with `UNAUTHORIZED` (P3.5 acceptance case b pending) | [Kyverno](../platform/kyverno.md) |
| 9 | (main) | Live k3s also runs `edge`, `kube-vip`, `kube-state-metrics` from branch `p3.3-edge-in-cluster`, and dgx-1's Wi-Fi interface carries 192.168.86.10 and .11. Expected while P3.3 is in progress; not on `main` yet | [DNS](../network/dns.md) |
| 10 | Design §4.2 / architecture §4.3: no service open to the LAN unless needed | LiteLLM :4000, Open WebUI :3100, Coolify :8000/6001/6002, Grafana :3000, Phoenix :6006, OTLP 4317–4320, Hermes :8642, control center :8200, fleet-metrics :9109 listen on all interfaces; Temporal and Zenoh have no auth | [Ports](../network/ports.md) |
| 11 | "Pin everything" (cluster/README, CI rules) | Hand-run containers use floating tags: `caddy:2.11` (edge-caddy), `nginx:alpine`, `home-assistant:stable`, `dgxmm:latest` | [Upgrades](../operations/upgrades.md) |
| 12 | (not documented) | dgx-1 runs an NFS server (2049, `nfs-mountd`) and `iperf3` (5201); the distro `lynis.timer` runs next to `lynis-audit.timer` on the Debian/Ubuntu hosts | [dgx-1](../hosts/dgx-1.md) |

## Documents that are behind or inconsistent

| # | Document | Says | Should say |
|---|---|---|---|
| 13 | `docs/project-plan.md` §2a | P3.2–P3.9 "wait on Ethernet"; P5.2 ⬜; P6.5 absent; Gatus and ntfy on dgx-2 (P1.6) | k3s built (#54), Argo CD (#57–#59), build-sign (#62–#64), governor built (#53, #60), MLflow (#52), alerting on the Dell (#55) |
| 14 | `runbooks/robot-ros.md` | the Zenoh Gatus check runs on dgx-2 from `playbooks/observe.yml` | the Dell, `playbooks/alerting.yml` |
| 15 | `runbooks/alerting.md` | "dgx-1 and dgx-2 only reach [the Dell] on 22 over Tailscale" | dgx-1 may reach `tag:agent` on 22 and 443; dgx-2 has no Tailscale grant to the Dell |
| 16 | `runbooks/README.md` | lists incident runbooks "to be written" and only some how-tos | it omits `age-key`, `aibom`, `build-sign`, `edge-connector`, `hermes-profiles`, `robot-ros`, `sign-in`, `temporal`, `web-https` |
| 17 | `README.md`, `docs/README.md`, `decisions/README.md` | decisions "D1–D23" / "D1–D19" | D1–D25 |
| 18 | `hosts/README.md` | "Roles today: base, tailscale, fleet_metrics"; mentions Tetragon; Jetson "etcd-only member" | 25 roles; no Tetragon; the Jetson is etcd + tainted worker |
| 19 | `policies/README.md` | Tailscale ACL "`tailscale.hujson`" | `policies/tailscale/policy.hujson` |
| 20 | `policies/defenseclaw/homelab.yaml` comment | LiteLLM gateway "(D18)" | D20 |
| 21 | `hosts/files/fleet-metrics/README.md` | deploy with `scp` and a user unit | Ansible role `fleet_metrics`, system unit, user `fleetmetrics` |
| 22 | `docs/architecture.md` §4.2 | `tag:admin` for the work Mac | no `tag:admin`; admins are `group:admins` |
| 23 | `docs/architecture.md` §12.2 | DefenseClaw dashboards provisioned from `cluster/observe/grafana/dashboards/defenseclaw/` | `hosts/stacks/observe/grafana/dashboards/defenseclaw/` |
| 24 | `docs/architecture.md` §3, §11 | SeaweedFS, CrowdSec, Tetragon, ARC runner, Gatus/ntfy on dgx-2 | not deployed (SeaweedFS, CrowdSec, Tetragon, ARC) or moved (Gatus/ntfy → Dell) |
| 25 | `agents/hermes/card.yaml` | `url: https://hermes.nghodki.ai/a2a` | placeholder; no DNS record |
| 26 | Decision 0006 | "two GPU/unified-memory OOMs took them down" | journals show NVRM OOMs on dgx-2 (2026-11-14 22:44, 2026-11-15 14:41) and dgx-1 (2026-11-15 14:46); both went down once, on 2026-11-15 |

## Not checked

- The laptop-side SSH tunnels (ports 2244, 2245, 2248).
- The Tailscale admin console (split DNS, the applied policy matches the file).
- LiteLLM's routes and image digest, DGXMM internals (owned by the DGXMM session).
- Certificate expiry dates for `nats.crt`, `fleet.crt`, `backup.crt`.
