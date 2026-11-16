---
title: Status
description: Where each plan phase stands on 2026-11-16, what is waiting on the user, and what is left from the DGXMM/LiteLLM session list.
---

Source: `docs/project-plan.md` §2a ("Status on 2026-11-16"). This page mirrors it; update both together.
Items marked "checked" were checked on the hosts that day.

Legend: ✅ done · 🟡 partly · ⏸️ prepared, waiting · ⬜ not started · 🔄 in progress (another session)

## Milestones

| Milestone | Meaning | State |
|---|---|---|
| M0 | No known critical/high finding open; every agent behind DefenseClaw 1.0.9 | mostly: F1–F5, F7, F8, F10 closed; F6 (dgx-1 single point of failure) narrowed: web and DNS run on both Sparks since the P3.3 cutover; NATS, Fleet, LiteLLM and DGXMM still need dgx-1 (P3.7) |
| M1 | Repo, CI, Ansible, bus and observability live | ✅ |
| M2 | Aliases, always-on robot and guard models, guardrail, Phoenix | guardrail ✅, Phoenix 🟡 (LiteLLM traces); aliases and models wait on P2.0 (you) |
| M3 | k3s with quorum, Argo CD deploys from Git, dgx-1 no longer a SPOF | k3s, Argo CD, Kyverno Enforce ✅; front door ✅; the rest is P3.7 (in progress) |
| M4–M6 | agents/tools/OpenBot; robot end to end; first trained policy on the robot | not started beyond the pieces below |

## Phase 0 (urgent fixes)

| ID | | Notes |
|---|---|---|
| P0.1 | ✅ | Pi backup on dgx-1 |
| P0.2 | ✅ | Pi on the 1 TB card, user `nikghodki-raspberry-1`, same Tailscale node |
| P0.3 | ✅ | DefenseClaw 1.0.9 for both Hermes users; skill-scanner LLM judge on for both (checked) |
| P0.4 | ✅ | Edge Connector 1.0.9 on the Pi, reporting to Fleet; picoclaw keeps its in-process hook |
| P0.5 | ✅ | Work-managed DefenseClaw removed from dgx-1; OSS 1.0.9 |
| P0.6 | ✅ | LiteLLM Postgres/Redis on 127.0.0.1 |
| P0.7 | ✅ | dead LiteLLM routes removed (checked: only live routes); nginx-gateway retired with the old front door (#88, #92) |
| P0.8 | ✅ | LiveKit key in a 0600 file; rotated |
| P0.9 | ✅ | DHCP reservations (Wi-Fi MACs); `pi.nghodki.ai` → .39 (#90, checked) |
| P0.10 | ✅ | Omarchy updated and on Tailscale (`tag:agent`) |
| P0.11 | ⬜ | Ethernet for the Sparks: **you** |
| P0.12 | ✅ | companion-agent retired; Jetson CDI fixed |
| P0.13 | ✅ | LiteLLM 1.109.1 by digest |
| P0.14 | ✅ | LiteLLM in Ansible; master and salt keys rotated into SOPS (#96) |
| P0.15 | ✅ | Second Hermes profile as `hermes-nikhil`; chat test still to do |
| P0.16 | ✅ | HA reverse-proxy settings; its trusted proxies still name dgx-1 from before the cutover (**you**) |
| P0.17 | ✅ | LiteLLM keys reviewed |

## Phase 1 (foundation)

| ID | | Notes |
|---|---|---|
| P1.1 | ✅ | repo, hardened settings, squash-only |
| P1.2 | ✅ | SOPS + age |
| P1.3 | ✅ | Ansible baseline on 5 hosts; weekly Lynis; hardening role (#70) |
| P1.4 | ✅ | Tailscale tags and policy applied and tested |
| P1.5 | ✅ | NATS on dgx-1; picoclaw connected; end-to-end reply still to test |
| P1.6 | ✅ | observe stack on dgx-2, collectors, GPU metrics, Fleet metrics |
| P1.7 | ✅ | alerts → ntfy end to end; alerting on the Dell (#55) with a dead man (#60); Pocket ID and Argo CD checks (#111) |
| P1.8 | ✅ | CI, hash-locked tools, Renovate |
| P1.9 | ✅ | GitHub Free (0001) |
| P1.10 | ⏸️ | backups "off" by 0002, **but live** ([Backups](../operations/backups.md)): **you** decide |
| P1.11 | ✅ | AIBOM (DefenseClaw + Cisco; the Jetson's images scanned on dgx-2), policy in Git, MCP tool pinning, LLM judge via LiteLLM |
| P1.12 | 🟡 | Fleet live; the Pi's SSH tunnel retired (#89); picoclaw on its in-process hook (OSS Fleet can't allow calls); upstream drafts not posted |
| P1.13 | 🟡 | Native OIDC: Grafana, Phoenix, Temporal, Argo CD, LiteLLM admin UI. Through edge-auth: docs, Homepage, Gatus, MLflow, DGXMM. Left: Open WebUI (family list, **you**) |
| P1.14 | ✅ | one Alertmanager; Gatus posts to ntfy directly |
| P1.15 | ✅ | Fleet Home; Homepage at `ops.nghodki.ai` |

## Phase 2 (model plane)

P2.0 ⬜ (**your decision**: models and aliases; until then `qwen3.8-27b` everywhere, decision 0012) · P2.4 ✅ (guardrail
on) · P2.6 🟡 (LiteLLM → Phoenix; agents not yet) · P2.1–P2.3, P2.5, P2.7, P2.8 ⬜ (DGXMM work; P2.5 and the memory
guards wait on **you**).

## Phase 3 (cluster and GitOps)

| ID | | Notes |
|---|---|---|
| P3.1 | ✅ | D2 confirmed and refined |
| P3.2 | ✅ | k3s over Wi-Fi (#54, decision 0005) |
| P3.3 | ✅ | kube-vip (VIPs .10 API, .11 edge), CoreDNS + Caddy in `edge` (#72, decision 0007); cut over 2026-11-15 (#78, #79); old door stopped (#92). Failover drill: platform session |
| P3.4 | ✅ | Argo CD + KSOPS (#57–#59) |
| P3.5 | ✅ (one user step) | Kyverno Enforce (#65, #68); `build-sign.yml` (#62–#64). The signed-image case waits for the GHCR packages to be **public** (you) |
| P3.6 | ⬜ | Tetragon |
| P3.7 | 🔄 | workloads into k3s (platform session) |
| P3.8 | ⬜ | etcd/CNPG backups to SeaweedFS |
| P3.9 | ⬜ | incident runbooks (see [Incident playbooks](../operations/incidents.md) for interim notes) |

## Phase 4 (agents, tools, OpenBot)

P4.1 ⏸️ (decision 0004 pending: **you**) · P4.3 ✅ (#67) · P4.7 ✅ (Temporal) · P4.9 ✅ (a2a-scanner, Agentic Radar) ·
P4.2, P4.4–P4.6, P4.8, P4.10–P4.13 ⬜.

## Phase 5 (robotics)

P5.1 ✅ (ROS 2 Kilted, `/scan` at 10.07 Hz) · P5.2 🟡 (governor built and deployed with a mock sink, #53, #60; picoclaw
and Hermes motion only through it, #73, #87; the on-blocks test needs **you**) · P5.3–P5.7 ⬜.

## Phase 6 (simulation and robot learning)

P6.2 ✅ (Isaac Lab) · P6.3 ⏸️ (Isaac Sim image exists, untested) · P6.4 ✅ (MuJoCo Playground) · P6.5 ✅ (MLflow, #52,
#66; policy videos still to do) · P6.1, P6.6–P6.12 ⬜.

## Waiting on the user

1. Revoke the old OpenRouter key; set the LiteLLM admin password; rotate the AWS Bedrock token.
1. Make the GHCR packages `mlflow` and `ros-zenoh` public (P3.5, decision 0008).
1. Home Assistant trusted proxies for the k3s front door (P0.16).
1. Backups: running vs decision 0002 (P1.10).
1. P0.11: cable the Sparks' 10 GbE ports.
1. P2.0: choose models and alias names; DGXMM pickle gap (P2.5) and memory guards (P2.7).
1. Decision 0004: OpenBot path (P4.1).
1. Robot: the on-blocks test (P5.2), the e-stop latch across restarts (code review #1/#12), firmware auth on the car.
1. The Open WebUI family list (P1.13).
1. Code review: LAN exposure binding (#33, #36, #37), log rotation (#28), Debian point releases (#21).
1. `externalTrafficPolicy: Local` on the edge Services.
1. Whether to post the 8 upstream issue drafts (`docs/upstream-issues/`).
1. In the monthly window: the Jetson's kept-back `linux-firmware` and a reboot.
1. Purchases: a UPS, an SSD for the Dell (design R10, R5); the Fleet Console design (D23).

## Still to do from the DGXMM/LiteLLM session list

- Done 2026-11-15: P0.14, dead routes, P2.4, P2.6 (LiteLLM), P1.11 judge, the skill-scanner judge on both Jetson users,
  sign-in for the LiteLLM admin UI and DGXMM.
- picoclaw end-to-end reply over NATS and the Hermes chat tests (both profiles): both agents have motion tools (through
  the governor), so run them with you present or the tools disabled.
- Open WebUI sign-in, after the family list.
- P2.0, then P2.1–P2.3, P2.5, P2.7, P2.8.
