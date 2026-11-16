---
title: Decisions
description: One line for every design decision (D1–D27) and every decision record (0001–0010), with its status.
---

Design decisions are in `docs/design.md` §6; later decisions are files in `decisions/` (template `0000-template.md`).

## Design decisions D1–D27

| # | Topic | Choice | Status |
|---|---|---|---|
| D1 | Orchestration | k3s | built (P3.2) |
| D2 | Control plane | dgx-1 and dgx-2 servers; the Jetson an etcd member **and** a tainted worker (`nghodki.ai/jetson=true:NoSchedule`, `role=edge-robot`) | built; worker role decided 2026-11-15 |
| D3 | GPU ownership | DGXMM keeps it; KServe under DGXMM later | decided; KServe draft on a DGXMM branch |
| D4 | Model access | agents call LiteLLM aliases, never models; which models and alias names: open | mechanism decided; aliases open (P2.0) |
| D5 | Message bus | NATS JetStream with MQTT | built (single node) |
| D6 | Robot transport | ROS 2 over Zenoh | built (P5.1) |
| D7 | Agent security | every DefenseClaw capability on every connected agent | partly: hooks, policy, Fleet/Edge, AIBOM, dashboards; not: guardrail plugin, judge, webhooks, Tetragon, sandboxes |
| D8 | Metrics | VictoriaMetrics | built |
| D9 | Logs and traces | Loki + Tempo | built |
| D10 | Dashboards | Grafana + DefenseClaw dashboards (not Splunk) | built |
| D11 | LLM tracing | Phoenix | up; no senders yet |
| D12 | Uptime and alerts | Gatus + vmalert → Hermes (WhatsApp) + ntfy | built with ntfy; WhatsApp not yet |
| D13 | Computer-use agent | CopilotKit/OpenBot on Omarchy | blocked: decision 0004 proposes cua + OpenShell |
| D14 | CI | GitHub Actions hosted; self-hosted ARC runner on dgx-2 for red-team | hosted done; runner not yet (P4.8) |
| D15 | Deployment direction | Argo CD pulls; Ansible runs from home; GitHub never gets in | built |
| D16 | Secrets | SOPS + age, key offline | built; key also in the cluster since 0006 |
| D17 | Pi storage | 1 TB card, fresh OS, restored | done (P0.2) |
| D18 | MacBook Air | left alone | in force |
| D19 | Vision | not deployed | in force; `vision-service` on the Jetson disabled under D26 |
| D20 | Tool and agent gateway | LiteLLM as MCP and A2A gateway, per-key tool permissions, `pre_mcp_call` guardrail | decided; not built (P4.2, P4.10) |
| D21 | Simulation | Isaac Lab 3.0, Isaac Sim when needed, MuJoCo, MLflow, ONNX → TensorRT/ONNX Runtime | Isaac Lab, MuJoCo, MLflow running |
| D22 | Sign-in | Pocket ID (passkeys), oauth2-proxy for apps without OIDC | built for 7 apps |
| D23 | Single pane of glass | standalone Fleet Console at `ops.nghodki.ai`; Homepage until then; one Alertmanager; Fleet Home | Homepage and Fleet Home built; console UI design open |
| D24 | DefenseClaw Fleet transport | dedicated Mosquitto broker on 8884, Caddy API proxy on 8971 | built |
| D25 | HTTPS for `*.nghodki.ai` | name-constrained homelab web CA + wildcard; install from `ca.nghodki.ai` | built |
| D26 | Voice and vision | retired for now: `voice-agent.nghodki.ai` off the front door and DNS (both doors), `vision-service` disabled; LiveKit and the control center stay on the Jetson; bring back only with a new decision | done (#75, #76) |
| D27 | PaaS | Coolify retired (decision 0010): it hosted no apps; containers, data, SSH key, route and DNS name removed | done |

The design doc's table header says "D1–D23" in places (README, `decisions/README.md`); D24–D27 were added later.

## Decision records

| # | Title | Date | Status | In one line |
|---|---|---|---|---|
| 0001 | GitHub Free | 2026-11-15 | decided | No GitHub Pro; merge only when `gh pr checks --watch` passes; long jobs go to the self-hosted runner |
| 0002 | Backups off for now | 2026-11-15 | decided | restic setup stays merged but not deployed; off-site on hold (**live state differs**: backups run) |
| 0003 | Cisco AI Defense tools | 2026-11-15 | decided | In use: DefenseClaw, mcp-scanner, skill-scanner, a2a-scanner, AIBOM; planned: model-provenance-kit, pickle-fuzzer, project-quarry, adversarial-hubness-detector; the cloud `ai-defense-*` clients not adopted (no tenant) |
| 0004 | OpenBot licensing | 2026-11-15 | **proposed, pending (user)** | OpenBot needs closed CopilotKit Intelligence; recommend cua + NVIDIA OpenShell |
| 0005 | k3s over Wi-Fi | 2026-11-15 | decided | Build now; Spark-to-Spark on the cable, Jetson and Dell over Wi-Fi with /32 routes; risks and wired migration listed |
| 0006 | GitOps platform | 2026-11-15 | decided; Kyverno parts replaced by 0008 | Argo CD 3.6 (Helm, self-managed, app of apps), KSOPS, the age key in the cluster, Kyverno in Audit in its own namespace, CNPG operator, single replicas, fixed ClusterIPs, ~2.5 GiB budget |
| 0007 | The front door in k3s | 2026-11-15 | decided; built (#72), cut over (#78, #79) | kube-vip ARP on the Sparks' Wi-Fi (VIPs 192.168.86.10 API, .11 edge); CoreDNS + Caddy in `edge`, 2 replicas each, routes and names in Git; the tailnet via the Sparks' Tailscale IPs (each CoreDNS replica answers with its own Spark), not a subnet route; kube-state-metrics; `edge` stays out of Kyverno's webhooks; edge-caddy stays as the nginx-gateway relay and rollback; CrowdSec waits |
| 0008 | Image signing and Enforce | 2026-11-15 | decided | cosign keyless from `build-sign.yml` on `main`; mlflow and ros-zenoh for amd64+arm64, packages public; MuJoCo stays local; Kyverno Enforce everything with failurePolicy Fail except kube-system, kyverno, argocd (and `edge`, kept out by 0007); `verify-images` with `mutateDigest`; new `require-image-digest`; 2 admission replicas |
| 0009 | No services box | 2026-11-15 | decided | Services stay on the Sparks (alerting on the Dell); hard reserves and job caps instead; revisit after another crash |
| 0010 | Retire Coolify | 2026-11-15 | decided; done | Coolify (0 apps) removed from dgx-1 with its data, SSH key, route and DNS name; nothing kept |

## Open questions (design §11)

1. Fleet Console UI/UX design.
2. Models and alias names (D4, P2.0).
3. GitHub Pro (answered: no, decision 0001).
4. Off-site backup target (on hold).
5. When to bring vision back, and where (D26: voice too, with a new decision).
6. CopilotKit Intelligence licensing (decision 0004).
