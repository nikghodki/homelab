# Home AI Fleet: Design Document

| | |
|---|---|
| Owner | nikghodki |
| Status | Draft v1.1, 2026-11-15 |
| Related | [architecture.md](architecture.md) (how it is built), [project-plan.md](project-plan.md) (how we get there) |

This document says **what** the system must do and **why** each major choice was made. The architecture
document describes the components and how they connect. The project plan describes the order of work.

**Changes 2026-11-15:** D2 now makes the Jetson an etcd member **and** a tainted worker for robot, home and agent
pods (it already hosted Hermes, the Zenoh router and a NATS replica, which an etcd-only member can't run). Device
roles (§7) and the Jetson capacity line (§9) follow.

---

## 1. Purpose

Six home devices already run useful pieces independently:

- **DGXMM, LiteLLM, Open WebUI and Coolify** on dgx-1
- **Hermes** on the Jetson
- **picoclaw** on the Raspberry Pi
- **Omarchy** on the Linux laptop

The goal is to turn them into **one fleet**: easy to change, safe to give agents real tools and a robot, able to
survive any single machine rebooting, and easy to grow.

## 2. Scope

**In scope:**
- dgx-1
- dgx-2
- the Jetson Orin
- the Raspberry Pi 4
- the Omarchy laptop (Dell Inspiron 7348)
- the network between them (LAN, Tailscale and the direct Spark-to-Spark cable)
- a private GitHub repo, `nikghodki/homelab`

**Out of scope, for now:**
- **The MacBook Air** ("leave it alone"). It keeps its own OpenClaw, Ollama and Supabase. See risk R7.
- **The vision service.** It isn't needed for now, and can be restored from the backup.
- The work Mac, beyond being the admin console.

## 3. Current state (inventory, 2026-11-14)

| Device | Hardware | Runs today |
|---|---|---|
| dgx-1 `spark-83dc` (.44) | GB10, 20 cores, 121 GiB unified memory, 3.7 TB NVMe | DGXMM, LiteLLM (+ Postgres, Redis), Open WebUI, Coolify, edge DNS + proxy, DefenseClaw (managed, 1.0.2), fleet-metrics |
| dgx-2 (.36) | GB10, 20 cores, 121 GiB, 3.7 TB NVMe | Nothing (idle) |
| Spark ↔ Spark | 2 × 200 Gb/s RDMA, 10.100.136/137.x | Only used for manual tests that split a model across both |
| Jetson `nikhil-jetson` (.211) | Orin, 6 cores, 7.4 GiB, 3.6 TB NVMe, JetPack 7.2.1 | Hermes (2 profiles), Home Assistant, roboclaw control center, vision-service, LiveKit |
| Omarchy `nikghodki-omarchy-local` (.49) | Dell Inspiron 7348 (2015): i5-5200U 2c/4t, 8 GB soldered, 500 GB 5400 rpm HDD, Wi-Fi | A desktop only; Tailscale stopped |
| Pi `nikraspberry` (.39) | Pi 4, 4 cores, 3.7 GiB; 32 GB SD at 75% (being replaced with 1 TB); LiDAR, IMX219 camera | picoclaw + DefenseClaw Lite hook, vision-ai, fleet-metrics |

Every device except the direct Spark link is on Wi-Fi.

**Problems found:**

| # | Problem | Severity |
|---|---|---|
| F1 | The Jetson DefenseClaw gateway isn't running, and the Hermes hook **fails open**. Hermes has run unchecked since 12 Nov. | Critical |
| F2 | The LiteLLM Postgres (5432) and Redis (6379) listen on all interfaces | High |
| F3 | picoclaw's only input channel points at an MQTT broker that doesn't exist (the Pi's old IP), and accepts commands from anyone | High |
| F4 | The LiveKit API secret is visible in the process list on the Jetson | High |
| F5 | DefenseClaw versions are old (1.0.2, a dev build, a custom Lite build); the latest is 1.0.9. Nothing on Omarchy. | High |
| F6 | dgx-1 is a single point of failure: DNS, proxy, model gateway and UIs all depend on it | High |
| F7 | Two dead LiteLLM routes; `nginx-gateway` crash-looping (117 restarts) | Medium |
| F8 | IPs change (the Pi moved from .34 to .39), breaking DNS and picoclaw's config | Medium |
| F9 | Pi SD card 75% full; Omarchy on a slow hard disk | Medium |
| F10 | The Jetson's `companion-agent.service` fails; the skill scanner fails on the `web` skill | Low |

## 4. Requirements

### 4.1 Functional
1. **Models.** Any agent can use chat, coding, vision, embeddings, speech and safety models by capability name,
   with automatic fallback.
2. **Agents.** Hermes, picoclaw, OpenBot (on Omarchy) and future agents can delegate to each other (A2A) and use
   shared tools (MCP), both through the LiteLLM gateway with per-agent permissions, and keep memory.
3. **Computer use.** OpenBot gets its own sandboxed computer (browser, files, shell) on Omarchy.
4. **Home and robot.** Agents can control Home Assistant and send goals to the robot. The robot keeps itself safe
   on its own.
6. **Robot learning.** Robot control and navigation policies (neural networks) are trained in simulation, in
   **Isaac Sim / Isaac Lab** and **MuJoCo**, on the Sparks. They are evaluated in simulation, tracked and versioned,
   and reach the real robot only through staged safety gates, always under the Pi's safety governor.
5. **Heavy work.** Batch evaluations, red-team runs and fine-tuning run on dgx-2. Very large models can run
   across both Sparks.

### 4.2 Non-functional

| Area | Requirement |
|---|---|
| Availability | Any **one** machine can reboot without losing DNS, the proxy, the message bus, the model gateway or the cluster |
| Security | Every agent's LLM and tool calls pass through DefenseClaw. Physical, write and irreversible actions **fail closed**. No service is open to the LAN unless it has to be. |
| Change control | Every change is a Git PR checked by CI; nothing is hand-edited except in emergencies |
| Operability | **One pane of glass** (Fleet Console) for health, security, models, agents, robot, deploys, alerts and approvals, with one sign-in (Pocket ID); alerts reach the phone even if the Jetson is down |
| Recoverability | Every stateful item is backed up (3-2-1); restores are tested monthly |
| Capacity | Fits the current hardware (the only purchases are a UPS and an SSD for the Inspiron) |
| Cost | Free or open-source tools; GitHub Free (Pro optional) |
| Robot safety | Loss of network or of any upstream service stops or slows the robot within 2 s |

## 5. Principles

1. **One front door per kind of request:** models, tools (MCP) and agent-to-agent calls (A2A) through LiteLLM;
   events through NATS.
2. **Names, not IPs.**
3. **Git is the source of truth.** Argo CD applies the cluster and Ansible applies the hosts.
4. **Agents ask for capabilities, not machines.**
5. **The fastest loops run closest to the hardware.**
6. **Least privilege:** one identity per agent and device, with only the tools and topics it needs.
7. **Fail closed** for anything with consequences; **fail visible** (with an alert) for everything else.

## 6. Key decisions

| # | Decision | Choice | Alternatives considered | Reason | Status |
|---|---|---|---|---|---|
| D1 | Orchestration | **k3s** (lightweight Kubernetes) | Docker Compose + Ansible; Nomad | Self-healing, scheduling by label, declarative, Git-driven; lightweight on ARM | Decided |
| D2 | Control plane | **2 servers: dgx-1 and dgx-2**, plus the Jetson as **etcd member + tainted worker for robot/agent pods** (taint `nghodki.ai/jetson=true:NoSchedule`, label `nghodki.ai/role=edge-robot`; no API server, scheduler or controllers) | 3 full servers; 2 servers with external Postgres; Omarchy as a server; etcd-only Jetson | Your choice of 2 servers. A 2-member etcd stops on any reboot, so a ~300 MB etcd member on the Jetson keeps quorum. Omarchy's hard disk is too slow for etcd. **Changed 2026-11-15:** the plan also puts the Zenoh router, Nav2 bridge, Home Assistant, a NATS replica and (after P4.5) Hermes on the Jetson, so it must also be a worker. The taint keeps everything else off, and tight limits protect etcd. Hermes and DefenseClaw stay host-installed until P4.5. | Decided (witness confirmed 2026-11-14; worker role 2026-11-15) |
| D3 | GPU ownership | **DGXMM keeps it**; KServe is added under DGXMM later | KServe alone; KServe + Knative | KServe can't fit models into GB10 unified memory or hold requests while models load. DGXMM's planner does both. KServe adds declarative serving. | Decided; draft on DGXMM branch `feature/kserve-backend` |
| D4 | Model access | **Agents call models through LiteLLM aliases** (capability names), never a model directly. **Which models, and the alias names, are decided later** (open question). | Agents call models directly | Swap models without touching agents; budgets and fallbacks | Mechanism decided; models and aliases open |
| D5 | Message bus | **NATS JetStream with MQTT enabled** | Mosquitto only; Redis | One bus for events and notifications (request/reply between agents goes through LiteLLM A2A, D20); MQTT clients (picoclaw, HA) connect unchanged; per-account limits | Decided |
| D6 | Robot transport | **ROS 2 over Zenoh** | Plain DDS | Works across Wi-Fi | Decided |
| D7 | Agent security | **Use every DefenseClaw capability on every connected agent** (DefenseClaw 1.0.9+): hook connectors for Hermes and the coding agents; the **Edge Connector** for picoclaw on the Pi, escalating to a DefenseClaw Fleet gateway over MQTT; the **agent-gateway route** for LiteLLM (model, MCP and A2A calls) and OpenBot; guardrails with rule packs, CEL/OPA policies, protected files and an LLM judge running on our own models; HITL approvals; admission scanning of skills, MCP servers and plugins (skill-scanner, mcp-scanner, plugin scanner, registries); **AI discovery and a nightly AIBOM** per host; OpenShell sandboxes; **Tetragon** kernel controls; hook guardian and foreign-hook guard; webhooks; and **all 19 DefenseClaw Grafana dashboards plus its alert rules**. Full map: architecture section 12.2. | Guardrail only; a self-built LiteLLM plugin calling the inspect API | One product covers hooks, edge, gateway, scanning, inventory, kernel controls and dashboards; the agent-gateway route is the supported way for LiteLLM and OpenBot | Decided 2026-11-14 |
| D8 | Metrics | **VictoriaMetrics** (Prometheus-compatible) | Prometheus | Lower RAM, same query language, keeps `fleet-metrics` | Decided |
| D9 | Logs and traces | **Loki + Tempo** | VictoriaLogs; SigNoz; Splunk | DefenseClaw ships 18 Grafana dashboards built on Loki and Tempo | Decided |
| D10 | Dashboards | **Grafana** + DefenseClaw dashboards | Splunk Free (DefenseClaw bundle) | Splunk Free: proprietary, ~500 MB/day, no alerting, no login, x86-only image | Decided |
| D11 | LLM tracing | **Phoenix** | Langfuse; Opik | One container, OpenTelemetry-native | Decided |
| D12 | Uptime and alerts | **Gatus** + vmalert → Hermes (WhatsApp) + **ntfy** backup channel | Uptime Kuma | Config in Git; alerts still arrive if the Jetson is down | Decided |
| D13 | Computer-use agent | **CopilotKit/OpenBot on Omarchy**: per-bot computer (container with Chromium, `/workspace`, bash), optional gVisor, per-bot egress policy, policy gateway, audit log | nightly-labs/openbot; trycua/cua; OpenHands | Your choice. Its model is pluggable (`OPENAI_BASE_URL` → LiteLLM). It needs CopilotKit Intelligence, and its Helm chart is amd64-only, which fits Omarchy. | Decided 2026-11-14 |
| D14 | CI | **GitHub Actions** (hosted runners) for static checks; a **self-hosted runner (ARC) on dgx-2** for red-team runs that need the home models | Everything at home | No installs at home for static tools; red-team runs need LiteLLM and run for hours | Decided; GitHub Pro (enforced checks) pending |
| D15 | Deployment direction | **Argo CD pulls from GitHub**; Ansible runs from home | GitHub pushes to the cluster | GitHub never gets a way into the network | Decided |
| D16 | Secrets | **SOPS + age**; the age key stays offline and never goes to GitHub | Vault/OpenBao | Simple and Git-native | Decided |
| D17 | Pi storage | **1 TB card, fresh Raspberry Pi OS Lite**, restored from backup without vision | Clone | macOS blocked raw writes; a fresh OS is cleaner | In progress |
| D18 | MacBook Air | **Left alone** | Manage it | Your choice | Decided |
| D20 | Tool and agent gateway | **LiteLLM as the MCP gateway and A2A agent gateway** (no separate LiteLLM MCP gateway): MCP servers registered once; each agent's LiteLLM key carries its allowed MCP servers and tools (`mcp_access_groups`, `mcp_tool_permissions`); a `pre_mcp_call` guardrail runs the DefenseClaw check and approvals; agents call each other through LiteLLM A2A | A separate MCP LiteLLM MCP gateway; NATS request/reply | One identity, one policy point, one audit trail and one trace for models, tools and agents; fewer components. LiteLLM doesn't detect tool-description changes, so the nightly scanner job stays. | Decided 2026-11-14 |
| D21 | Simulation and robot learning | **Isaac Lab 3.0** (supports DGX Spark/aarch64; Newton physics, headless) for parallel RL training; **Isaac Sim** (a version Isaac Lab 3.0 supports, i.e. newer than 5.1) when realistic camera/LiDAR rendering is needed; **MuJoCo** (MuJoCo Playground on MJX, or MuJoCo Warp) for fast control-policy training and cross-checking policies in a second simulator; **MLflow** on dgx-2 for experiments and the policy registry; policies exported to **ONNX → TensorRT** (Jetson) or ONNX Runtime (Pi) | Gazebo; Isaac Sim only; cloud GPUs | Both simulators run on the Sparks; testing a policy in two simulators catches simulator-specific tricks before real tests; MLflow is free, self-hosted and well supported | Decided 2026-11-14 |
| D22 | Sign-in (one login for every UI) | **Pocket ID**: passkey-only OIDC provider (one small container). Apps with OIDC (Grafana, Argo CD, Open WebUI, Gatus, Headlamp, Phoenix, LiteLLM UI, Fleet Console) use it directly; apps without (Home Assistant, DGXMM UI) sit behind Caddy with **oauth2-proxy** (or tinyauth) using Pocket ID | Authentik; Tailscale identity headers only | One user, passkeys, tiny footprint; Authentik's SAML/LDAP and policy engine aren't needed | Decided 2026-11-14 |
| D23 | Single pane of glass | **Fleet Console**, a **standalone app** at `ops.nghodki.ai` behind Pocket ID: reads every system's API and offers the actions (approve, freeze agent, quarantine host, e-stop, load/unload model, roll back), each one checked by DefenseClaw and audited; embeds Grafana and Phoenix panels; "Ask the fleet" chat with read-only MCP tools. Underneath: **one Alertmanager** for every alert source, a **Fleet Home** Grafana dashboard with linked drill-downs, and a **Homepage** launcher until the console exists. **UI/UX design is to be decided later** (a throwaway demo is in `console-demo/`). | Grafana app plugin; Backstage; Grafana only | Grafana covers data but not actions or approvals; a standalone app is free to fit the workflow | Decided 2026-11-14; UI design open |
| D24 | DefenseClaw Fleet transport | **A dedicated Mosquitto broker** (`fleet.nghodki.ai:8884`, TLS, per-device ACLs) for Edge Connector Fleet traffic, not NATS: the Fleet gateway's Go client speaks only MQTT 5, and NATS MQTT is 3.1.1. NATS stays the general fleet bus. The Fleet API is served over TLS by a host-network Caddy on dgx-1 (`:8971`) that forwards only `/api/v1/fleet/*` to the loopback gateway |
| D25 | HTTPS for `*.nghodki.ai` | **A name-constrained homelab web CA** (only `nghodki.ai` names) plus a wildcard certificate on the dgx-1 front door; each device installs the CA once from `ca.nghodki.ai`. Chosen over registering the domain (Let's Encrypt) and over Tailscale `ts.net` names (2026-11-15). Kept separate from the internal homelab CA, which is never installed on phones. Risk: `nghodki.ai` is unregistered, so someone else could register it; registering it later moves us to Let's Encrypt |
| D19 | Vision | **Not deployed** for now | Move it to the Jetson | Not needed now | Decided |

## 7. Device roles

| Device | Role | k3s |
|---|---|---|
| dgx-1 | Interactive inference (chat, vision, speech, always-on robot and guard models); control plane | server |
| dgx-2 | Batch (evals, red-team, fine-tuning, **Isaac Lab/Sim and MuJoCo training**, MLflow); storage; observability and other heavy CPU services; self-hosted CI runner; control plane | server |
| Jetson | Home and robot brain: Hermes, Home Assistant, Nav2/SLAM, Zenoh router, LiveKit; **etcd member** | etcd member + tainted agent (robot, home and agent pods only) |
| Omarchy | OpenBot and its computer; light worker agents | agent |
| Pi | Robot body: drivers, safety governor, picoclaw reflexes | none (Ansible) |
| MacBook Air | Out of scope | none |

## 8. Security design (summary)

These are the layers, in order. Details are in architecture §12.

1. **Network:** Tailscale ACLs by tag; nothing listens on the LAN that doesn't need to; CrowdSec on the proxy.
2. **Identity:** one identity per agent and device (Tailscale tag, LiteLLM key, NATS user, tool scope).
3. **Supply chain:**
   - CI scans everything before it can merge: secrets, dependencies, code, images, Kubernetes manifests, skills,
     MCP servers, agent cards and model files.
   - Images are signed (cosign keyless), and Kyverno at home admits only signed images.
4. **Agent runtime:**
   - DefenseClaw hooks in Hermes, picoclaw, OpenBot and the coding agents.
   - DefenseClaw everywhere: hooks (Hermes, coding agents), the Edge Connector (picoclaw), the agent-gateway route
     (LiteLLM, OpenBot), admission scanning, AI discovery and AIBOM.
   - LiteLLM as the single gateway for models, MCP tools and A2A: per-agent keys carry allowed models, tools and
     agents; DefenseClaw (agent-gateway route) and guard models (Prompt Guard 2, a small Llama Guard or Granite
     Guardian) check every call; physical or irreversible tool calls wait for your approval.
5. **Host runtime:** Tetragon with DefenseClaw kernel controls; DefenseClaw hook guardian and foreign-hook guard;
   Kyverno; kube-bench and Lynis monthly.
6. **Testing:** garak weekly, promptfoo on every agent or prompt change, PyRIT monthly.
7. **Recovery:** encrypted backups; rebuilding anything from Git.
8. **Visibility:** the Security dashboard; alerts on any fail-open event or any DefenseClaw gateway going down.

## 9. Capacity (summary; estimates)

| Device | Planned use | Verdict |
|---|---|---|
| dgx-1 | ~97 of 121 GiB at a typical busy moment, assuming example models (D4 is open); the rest is headroom for swapping a model and load spikes (can go to ~113) | OK |
| dgx-2 | 15–23 GiB reserved for services; 80–90 GiB for batch work, shared by LLM evals and simulation (est. 20–60 GiB per sim job, depending on the number of parallel environments and on cameras); dgx-1 takes overnight sim jobs when idle | OK; the reserve must be enforced; one large sim job at a time |
| Jetson | ~5.5 GiB with the etcd member, Nav2 and its few tolerated pods (with limits), without the desktop or vision | OK if headless |
| Omarchy | ~5.5–6.5 of 7.7 GiB; one OpenBot desktop at a time; 2 cores are the real limit | Tight; SSD recommended |
| Pi | ~1 GiB without vision; 1 TB card fixes storage | OK |

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | The Jetson is a quorum member *and* runs the home and robot; if it is down during a Spark reboot, the cluster stops accepting changes | Schedule Spark maintenance only when the Jetson is healthy; running services keep working without quorum |
| R2 | Wi-Fi drops affect the Jetson, Pi and Omarchy | Sparks on Ethernet; robot fails safe; IP reservations |
| R3 | A batch job on dgx-2 starves services that share its unified memory | DGXMM reserve plus pod memory limits |
| R4 | GB10 memory bandwidth is shared, so `robot-fast` slows while `smart` generates | Decider priorities; measure p95 latency; move `robot-fast` to dgx-2 if needed |
| R5 | Omarchy too weak for OpenBot computers | One computer at a time; SSD; OpenBot images are amd64-only, so they can't move to the Sparks |
| R13 | Isaac Sim livestream, multi-node training, SkillGen, XR teleop and Cosmos Transfer aren't supported on DGX Spark (Isaac Lab 3.0 docs) | Run headless; record evaluation videos to MLflow; one Spark per training job |
| R14 | Sim-to-real gap: a policy that works in simulation fails on the real robot | Domain randomization; cross-check in both simulators; calibrate the simulation from real rosbags; staged real-world gates (shadow → on blocks → speed-capped → live) under the safety governor |
| R15 | Sim jobs and LLM batch jobs compete for dgx-2's memory | DGXMM budget covers sim jobs too; queue with priorities; overnight overflow to dgx-1 |
| R12 | LiteLLM becomes critical for models, tools and agent calls at once | 2 replicas, pinned release (today `main-latest` = 1.100.0), Postgres HA, same `LITELLM_SALT_KEY` on both replicas; robot safety stays local on the Pi |
| R11 | CopilotKit OpenBot needs CopilotKit Intelligence; the free local mode is documented as a macOS preview, and Linux means their managed service or a licensed self-hosted install | Confirm the licensing path in P4.1; fallback trycua/cua + OpenShell |
| R6 | KServe or vLLM images may not run on arm64 or GB10 | Pilot first; keep the Docker backend |
| R7 | The MacBook Air's OpenClaw is outside the fleet and unprotected (DefenseClaw removed 29 Sep) | Accepted for now; revisit |
| R8 | GitHub Free doesn't enforce required checks on private repos | GitHub Pro, or discipline: never merge red |
| R9 | Losing the age key makes every secret unrecoverable | Offline copy plus password manager; restore drill quarterly |
| R10 | No UPS: a power cut hard-stops every machine | Buy a UPS; NUT shutdown order |

## 11. Open questions

1. **Fleet Console UI/UX design** (D23): pages, layout and interactions; decided later.
2. **Models and their aliases:** which models to serve, and the alias names (D4). The names used elsewhere in
   these docs (`smart`, `robot-fast`, `guard` …) are placeholders, and the memory figures in section 9 assume
   example models.
3. **GitHub Pro** for enforced checks, or report-only checks?
4. **Off-site backup** target: on hold (2026-11-14).
5. When to bring back **vision**, and whether on the Jetson.
6. **CopilotKit Intelligence** licensing path on Linux (managed service or self-hosted license); see R11.
