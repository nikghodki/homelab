---
title: Status
description: Where each plan phase stands on 2026-11-15 (end of day), what is waiting on the user, and the "after the DGXMM session" list.
---

Source: `docs/project-plan.md` §2a ("Status on 2026-11-15 (evening)"), corrected with what merged after it was written
(PRs #52–#79) and the live state. Where this page and §2a differ, this page is newer; the differences are listed at the
bottom.

Legend: ✅ done · 🟡 partly · ⏸️ prepared, waiting · ⬜ not started · 🔄 in progress (another session)

## Milestones

| Milestone | Meaning | State |
|---|---|---|
| M0 | No known critical/high finding open; every agent behind DefenseClaw 1.0.9 | mostly: F1–F5, F8, F10 closed; F6 (dgx-1 single point of failure) narrowed by the P3.3 cutover (web and DNS on both Sparks; nginx-gateway routes, NATS, Fleet, LiteLLM still on dgx-1, P3.7); F7 half (dead routes; the voice route is gone, D26) |
| M1 | Repo, CI, Ansible, bus and observability live | ✅ |
| M2 | Aliases, always-on robot and guard models, guardrail, Phoenix | blocked on P2.0 and the DGXMM session |
| M3 | k3s with quorum, Argo CD deploys from Git, dgx-1 no longer a SPOF | k3s, Argo CD, Kyverno Enforce ✅; SPOF removal: P3.3 ✅ for web and DNS; the rest is P3.7 |
| M4–M6 | agents/tools/OpenBot; robot end to end; first trained policy on the robot | not started beyond the pieces below |

## Phase 0 (urgent fixes)

| ID | | Notes |
|---|---|---|
| P0.1 | ✅ | Pi backup on dgx-1 |
| P0.2 | ✅ | Pi on the 1 TB card, user `nikghodki-raspberry-1`, same Tailscale node |
| P0.3 | ✅ | DefenseClaw 1.0.9 for both Hermes users; skills recovered after the PATH outage; skill-scanner judge off for now |
| P0.4 | ✅ | Edge Connector 1.0.9 on the Pi, reporting to Fleet; picoclaw keeps its in-process hook |
| P0.5 | ✅ | Work-managed DefenseClaw removed from dgx-1; OSS 1.0.9 |
| P0.6 | ✅ | LiteLLM Postgres/Redis on 127.0.0.1 |
| P0.7 | 🟡 | nginx-gateway fixed and kept; dead LiteLLM routes still there |
| P0.8 | ✅ | LiveKit key in a 0600 file; rotated |
| P0.9 | ✅ | DHCP reservations (Wi-Fi MACs). But `pi.nghodki.ai` still points at .34 |
| P0.10 | ✅ | Omarchy updated and on Tailscale (`tag:agent`) |
| P0.11 | ⬜ | Ethernet for the Sparks — **you** |
| P0.12 | ✅ | companion-agent retired; Jetson CDI fixed |
| P0.13 | ✅ | LiteLLM 1.109.1 by digest |
| P0.14 | ⬜ | LiteLLM master/salt key rotation into SOPS — after the DGXMM session |
| P0.15 | ✅ | Second Hermes profile as `hermes-nikhil` |
| P0.16 | ✅ | HA reverse-proxy settings |
| P0.17 | ✅ | LiteLLM keys reviewed |

## Phase 1 (foundation)

| ID | | Notes |
|---|---|---|
| P1.1 | ✅ | repo, hardened settings, squash-only |
| P1.2 | ✅ | SOPS + age |
| P1.3 | ✅ | Ansible baseline on 5 hosts; weekly Lynis; hardening role after the first audit (index 59–68 → 65–72, #70) |
| P1.4 | ✅ | Tailscale tags and policy applied and tested |
| P1.5 | ✅ | NATS on dgx-1; picoclaw connected. End-to-end reply waits for the model |
| P1.6 | ✅ | observe stack, collectors, GPU metrics, Fleet metrics |
| P1.7 | ✅ | alerts → ntfy end to end; alerting moved to the Dell (#55) with a dead man (#60) |
| P1.8 | ✅ | CI, hash-locked tools, Renovate |
| P1.9 | ✅ | GitHub Free (0001) |
| P1.10 | ⏸️ | backups "off" by 0002 — **but live** (see below) |
| P1.11 | 🟡 | AIBOM (DefenseClaw + Cisco), policy in Git, bundle sync, MCP tool pinning; still: LLM judge via LiteLLM |
| P1.12 | 🟡 | Fleet live; picoclaw on its in-process hook (OSS Fleet can't allow calls); upstream drafts not posted |
| P1.13 | 🟡 | Pocket ID for Grafana, Gatus, Phoenix, Temporal, Homepage, MLflow, Argo CD; LiteLLM UI, DGXMM UI, Open WebUI after DGXMM |
| P1.14 | ✅ | one Alertmanager; Gatus posts to ntfy directly |
| P1.15 | ✅ | Fleet Home; Homepage at `ops.nghodki.ai` |

## Phase 2 (model plane)

P2.0 ⬜ (**your decision**: models and aliases) · P2.4 🟡 (guardrail written, not enabled) · P2.6 🟡 (Phoenix up, no
senders) · P2.1–P2.3, P2.5, P2.7, P2.8 ⬜ (DGXMM work).

## Phase 3 (cluster and GitOps)

| ID | | Notes |
|---|---|---|
| P3.1 | ✅ | D2 confirmed and refined |
| P3.2 | ✅ | k3s over Wi-Fi (#54, decision 0005) — §2a still says "waits on Ethernet" |
| P3.3 | ✅ (two follow-ups) | kube-vip (VIPs 192.168.86.10 API, .11 edge), CoreDNS + Caddy in `edge`, kube-state-metrics; Gatus group `edge`; vmalert `front-door` rules (#72, decision 0007; voice route dropped in #76). **Cut over 2026-11-15**: Tailscale policy for both Sparks (#78), dgx-2 as a second split-DNS nameserver (console; live), #79 (dgx-1's Tailscale IP on the tailnet Services, k3s DNS → edge-dns, Gatus via the VIP, front-door alerts critical). edge-caddy on dgx-1 stays as the nginx-gateway relay and rollback. Left: the check from a family device (**you**) and a tailnet failover drill a day later (`runbooks/edge.md`, "Cutover" steps 5–6) |
| P3.4 | ✅ | Argo CD + KSOPS (#57, #58, #59) |
| P3.5 | ✅ (one user step) | Kyverno Enforce with 6 policies incl. `verify-images`, 2 admission replicas (#65, #68); `build-sign.yml` with cosign keyless (#62–#64). Acceptance done except the signed-image case: the GHCR packages must be made **public** (you) |
| P3.6 | ⬜ | Tetragon |
| P3.7 | ⬜ | workloads into k3s |
| P3.8 | ⬜ | etcd/CNPG backups to SeaweedFS |
| P3.9 | ⬜ | incident runbooks (see [Incident playbooks](../operations/incidents.md) for interim notes) |

## Phase 4 (agents, tools, OpenBot)

P4.1 ⏸️ (decision 0004 pending — **you**) · P4.3 ✅ (MCP admission registry in DefenseClaw on the Jetson and the nightly
drift check, #67; LiteLLM registration waits for P4.2) · P4.7 ✅ (Temporal) · P4.9 ✅ (a2a-scanner, Agentic Radar) ·
P4.2, P4.4–P4.6, P4.8, P4.10–P4.13 ⬜.

## Phase 5 (robotics)

P5.1 ✅ (ROS 2 Kilted, `/scan` at 10.07 Hz) · P5.2 🟡 (governor built and deployed with a mock sink, #53, #60; picoclaw as
its own user with its motion tools through the governor's motion bridge, #73; the final on-blocks test needs **you**) —
§2a still says ⬜ · P5.3–P5.7 ⬜.

## Phase 6 (simulation and robot learning)

P6.2 ✅ (Isaac Lab) · P6.3 ⏸️ (Isaac Sim image exists, untested) · P6.4 ✅ (MuJoCo Playground) · P6.5 ✅ (MLflow, #52;
Isaac Lab RSL-RL and measure.sh log to it, #66; policy videos still to do) ·
P6.1, P6.6–P6.12 ⬜.

## Waiting on the user

1. Make the GHCR packages `mlflow` and `ros-zenoh` public (GitHub UI): until then Kyverno refuses every
   `ghcr.io/nikghodki` image (P3.5, decision 0008). Still private at check time (anonymous pull: 403).
1. P3.3 cutover step 5: from a family device, check that Home Assistant and Open WebUI open and ntfy alerts arrive.
1. P0.11: cable the Sparks' 10 GbE ports (then redo reservations and the k3s LAN settings).
2. P2.0: choose models and alias names.
3. Decision 0004: OpenBot path (recommended: cua + OpenShell).
4. The robot on-blocks test (P5.2 final check).
5. Backups: decide whether the running backups stay (and update 0002) or are turned off ([Backups](../operations/backups.md)).
6. Whether to post the 8 upstream issue drafts (`docs/upstream-issues/`).
7. Purchases: a UPS, an SSD for the Dell (design R10, R5).
1. In the monthly window: reboot the Jetson and install the kept-back `linux-firmware` there (Lynis KRNL-5830, PKGS-7392).
8. Fleet Console UI/UX design (D23).

## After the DGXMM session

- P0.14: rotate the LiteLLM master and salt keys into SOPS; remove dead routes (P0.7).
- P2.4 guardrail plugin on, P2.6 LiteLLM → Phoenix, P1.11 LLM judge.
- Skill scanner LLM judge back on for both Jetson users (`defenseclaw setup skill-scanner --use-llm`, then
  `skill scan all`).
- picoclaw end-to-end reply over NATS, and the Hermes chat tests (both profiles).
- P1.13 for LiteLLM UI, DGXMM UI and Open WebUI.
- P2.0 models and aliases (you), then P2.1–P2.3, P2.5 (model supply chain), P2.7, P2.8.
- A LiteLLM virtual key for Cisco AIBOM's LLM enrichment.

## Where §2a of the plan is behind

- P3.2 is done (k3s, #54), P3.4 done (#57–#59), P3.5 done (#57, #62–#65, #68): §2a says "P3.2–P3.9 wait on Ethernet".
- P3.3 is done (#72, #78, #79; cut over 2026-11-15): not in §2a.
- P4.3 is done (#67): not in §2a.
- P5.2 is built (#53, #60): §2a says ⬜.
- P6.5 is done (#52): not in §2a.
- P1.7/P1.14: alerting moved to the Dell (#55): §2a still places Gatus and ntfy on dgx-2 under P1.6.
