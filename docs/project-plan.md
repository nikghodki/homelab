# Home AI Fleet: Project Plan

| | |
|---|---|
| Owner | nikghodki (approves and merges) · operator: Claude Code (prepares PRs, runs checks) |
| Status | Draft v1, 2026-11-14; status (§2a) updated 2026-11-16 |
| Related | [design.md](design.md), [architecture.md](architecture.md) |

**Effort** is in sessions of about 2 hours, and is an estimate. **Weeks** assume a few evenings a week.
Each task has an acceptance check; a phase is done only when all its checks pass.

---

## 1. Timeline

```
Week:      1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16
Phase 0  ██                                                                 Urgent fixes
Phase 1      ██████                                                         Foundation
Phase 2              ██████                                                 Model plane
Phase 3                      ██████                                         Cluster + GitOps
Phase 4                              ██████████                             Agents, tools, OpenBot
Phase 5                                          ██████████                 Robotics
Phase 6                                  ░░░░░░  ████████████████████       Simulation + robot learning
KServe pilot (parallel, optional)        ░░░░░░░░
```
(░ = Phase 6 prep that can start early: robot description and simulator installs.)

| Milestone | Target | Meaning |
|---|---|---|
| M0 | End of week 1 | No known critical or high finding open; every agent is protected by DefenseClaw 1.0.9 |
| M1 | Week 3 | Repo, CI, Ansible, bus and observability live; you can see the whole fleet |
| M2 | Week 5 | Model aliases, always-on robot and guard models, guardrail, Phoenix |
| M3 | Week 7 | k3s with quorum; dgx-1 is no longer a single point of failure; Argo CD deploys from Git |
| M4 | Week 10 | LiteLLM MCP gateway, agent contract, OpenBot with its own computer, red-team in CI |
| M5 | Week 12 | Robot: safety governor, Zenoh, Nav2 goals from Hermes, end to end |
| M6 | Week 16 | First neural-network policy trained in simulation (Isaac Lab + MuJoCo), passed all gates, running on the robot |

## 2. Already done (2026-11-14)

| Item | Result |
|---|---|
| Inventory of all devices | Findings F1–F10 (design §3) |
| DGXMM KServe backend draft | Branch `feature/kserve-backend` on dgx-1 (uncommitted): `dgxmm/backend.py`, `dgxmm/kserve_ctl.py`, 9 tests passing, `docs/architecture/kserve-backend.md`. The rest of the suite passes except one timezone test that fails without these changes. |
| Design documents | `~/homelab/docs/` on dgx-1 (this set) |
| Pi backup | Running → `~/backups/nikraspberry-2026-11-14/pi-full.tar.zst` on dgx-1 |
| Pi 1 TB card | Being flashed with Raspberry Pi OS Lite (64-bit) in Raspberry Pi Imager |

## 2a. Status on 2026-11-16

Legend: ✅ done · 🟡 partly · ⏸️ prepared, waiting · ⬜ not started · 🔁 changed · 🔄 in progress (another session)

The docs site's Status page (`docs-site/content/docs/decisions/status.md`) mirrors this section.

### Phase 0
| ID | Status | Notes |
|---|---|---|
| P0.1 | ✅ | Pi backup on dgx-1 |
| P0.2 | ✅ | Fresh Pi OS on the 1 TB card, user `nikghodki-raspberry-1`, restored; same Tailscale node |
| P0.3 | ✅ | Jetson: DefenseClaw 1.0.9 for both Hermes users (action, fail closed, `homelab` policy). Skills recovered after the scanner-PATH outage (role `defenseclaw_gateway_env`, #45). Skill scanner LLM judge back on for both users (`use_llm: true`, `qwen3.8-27b`, decision 0012; checked 2026-11-16) |
| P0.4 | 🔁 ✅ | Production Edge Connector 1.0.9 on the Pi as `edge-connector.service`, reporting to Fleet (see P1.12). picoclaw keeps its in-process hook until upstream can allow escalated calls |
| P0.5 | 🔁 ✅ | Work-managed DefenseClaw + dcsidecar uninstalled; OSS 1.0.9 on dgx-1 |
| P0.6 | ✅ | LiteLLM Postgres/Redis on 127.0.0.1 |
| P0.7 | ✅ | Dead LiteLLM routes removed (only live routes in `/v1/models`, checked 2026-11-16); `nginx-gateway` retired with the old front door (#88, #92; container stopped) |
| P0.8 | ✅ | LiveKit key in a 0600 key file; rotated 2026-11-15; in SOPS (`secrets/voice.enc.yaml`) |
| P0.9 | ✅ | DHCP reservations (Wi-Fi MACs; wired MACs after P0.11); `pi`/`raspberrypi.nghodki.ai` → .39 (#90, checked at the VIP) |
| P0.10 | ✅ | Omarchy updated and on Tailscale (`nikghodki-omarchy`, tag:agent) |
| P0.11 | ⬜ | Ethernet for the Sparks (you) |
| P0.12 | ✅ | `companion-agent` retired; Jetson `nvidia-cdi-refresh` fixed (role `jetson_cdi`) |
| P0.13 | ✅ | LiteLLM 1.109.1 pinned by digest |
| P0.14 | ✅ | LiteLLM in Ansible; master and salt keys rotated into SOPS (#96) |
| P0.15 | ✅ | Profile nikhil-ghodki as Linux user `hermes-nikhil` with its own Hermes and DefenseClaw. runbooks/hermes-profiles.md. Chat test of both profiles still to do (see below) |
| P0.16 | ✅ | Home Assistant reverse-proxy settings in its UI. The trusted proxies still name dgx-1 (.44 and its Tailscale IP), from before the cutover; updating them waits on you |
| P0.17 | ✅ | Keys reviewed 2026-11-15 |

### Phase 1
| ID | Status | Notes |
|---|---|---|
| P1.1 | ✅ | `nikghodki/homelab`, hardened repo settings, squash-only |
| P1.2 | ✅ | SOPS + age; key saved offline (runbooks/age-key.md) |
| P1.3 | ✅ | Ansible baseline on all 5 hosts, idempotent; weekly Lynis; hardening role (#70) |
| P1.4 | ✅ | Tailscale tags and `policies/tailscale/policy.hujson` applied and tested |
| P1.5 | ✅ | NATS 2.15.3 on dgx-1 (TLS, MQTT over TLS, deny-by-default users); picoclaw connected as `picoclaw`. End-to-end reply still to test |
| P1.6 | ✅ | dgx-2: VictoriaMetrics, Loki, Tempo, Grafana, vmalert, Alertmanager; collectors + fleet-metrics on all 5 hosts; GPU and thermal metrics. Gatus and ntfy moved to the Dell (#55) |
| P1.7 | ✅ | Alerts → ntfy end to end; alerting on the Dell with a dead man (#55, #60); Pocket ID and Argo CD checks (#111) |
| P1.8 | ✅ | CI with hash-locked tools, unit tests, Renovate |
| P1.9 | ✅ | GitHub Free (decisions/0001); merge only when `gh pr checks --watch` passes |
| P1.10 | ⏸️ | Backups merged (#17). Decision 0002 says off, but they run (rest-server on dgx-2, nightly timers on 4 hosts): **you** decide which wins |
| P1.11 | ✅ | AIBOM (DefenseClaw nightly + Cisco AIBOM fleet, image scans for the Jetson on dgx-2, #85), OTLP + redaction, policy `homelab` in Git, MCP tool pinning, LLM judge via LiteLLM (#96). Webhooks dropped (private receivers refused) |
| P1.12 | 🟡 | Fleet live (gateway on dgx-1, Mosquitto TLS + ACLs, signed policy v1); the Pi's SSH tunnel retired (#89). picoclaw stays on its in-process hook (OSS Fleet can't allow calls). Upstream issue drafts not posted (you) |
| P1.13 | 🟡 | Pocket ID 2.19.3 at `id.nghodki.ai`. Native OIDC: Grafana, Phoenix, Temporal UI, Argo CD, the LiteLLM admin UI (#104). Through the one front-door proxy `edge-auth` (decision 0011): docs, Homepage, Gatus, MLflow, DGXMM (#91–#95, #100). Open WebUI is left (family list, you). HA keeps its own login (phone app) |
| P1.14 | ✅ | One Alertmanager for vmalert alerts; Gatus posts to ntfy directly |
| P1.15 | ✅ | Fleet Home dashboard; Homepage at `ops.nghodki.ai` behind edge-auth (#93) |

### Phase 2
| ID | Status | Notes |
|---|---|---|
| P2.0 | ⬜ | Models and aliases (your decision). Until then every consumer uses `qwen3.8-27b` (decision 0012) |
| P2.4 | ✅ | DefenseClaw guardrail plugin on in LiteLLM (#96) |
| P2.6 | 🟡 | Phoenix on dgx-2; LiteLLM sends traces (#96); agents not yet |
| P2.1–P2.3, P2.5, P2.7, P2.8 | ⬜ | DGXMM work (DGXMM session; P2.5 pickle gap and P2.7 memory guards wait on you) |

### Phase 3
| ID | Status | Notes |
|---|---|---|
| P3.1 | ✅ | D2 confirmed, then refined: Jetson = etcd member + tainted worker (#40) |
| P3.2 | ✅ | k3s over Wi-Fi (#54, decision 0005): servers on both Sparks, Jetson etcd + tainted worker, Omarchy agent |
| P3.3 | ✅ | Front door in k3s: kube-vip (VIPs .10 API, .11 edge), CoreDNS, Caddy (#72, decision 0007); cut over 2026-11-15 (#78, #79); old door stopped (#92). Failover drill: platform session |
| P3.4 | ✅ | Argo CD + KSOPS; merge-to-deploy 178 s (#57–#59) |
| P3.5 | ✅ | Kyverno Enforce, 6 policies, 2 admission replicas (#65, #68); `build-sign.yml` with cosign keyless (#62–#64). The signed-image acceptance case waits until the GHCR packages are public (you) |
| P3.6 | ⬜ | Tetragon |
| P3.7 | 🔄 | Workloads into k3s: platform session |
| P3.8 | ⬜ | etcd/CNPG backups to SeaweedFS (after P3.7) |
| P3.9 | ⬜ | Incident runbooks (interim notes in the docs site's Incident playbooks) |

### Phase 4
| ID | Status | Notes |
|---|---|---|
| P4.1 | ⏸️ | Proposal decisions/0004 (recommended: cua + NVIDIA OpenShell on Omarchy). Decision pending (you) |
| P4.3 | ✅ | MCP admission from Git and the nightly tool drift check (#67); LiteLLM registration waits for P4.2 |
| P4.7 | ✅ | Temporal 1.32.2 on dgx-2 (`jobs` stack), UI behind Pocket ID (#44) |
| P4.9 | ✅ | a2a-scanner on agent cards and Agentic Radar in CI |
| P4.2, P4.4–P4.6, P4.8, P4.10–P4.13 | ⬜ | |

### Phase 5
| ID | Status | Notes |
|---|---|---|
| P5.1 | ✅ | ROS 2 Kilted + rmw_zenoh; `/scan` at 10.07 Hz on the Jetson (#47) |
| P5.2 | 🟡 | Safety governor built and deployed on the Pi with a mock sink (#53, #60); picoclaw as its own user, motion only through the governor (#73); Hermes motion through it too (#87). The on-blocks test needs you |
| P5.3–P5.7 | ⬜ | |

### Phase 6
| ID | Status | Notes |
|---|---|---|
| P6.2 | ✅ | Isaac Lab 3.0.0 headless on dgx-2 (#48) |
| P6.3 | ⏸️ | Isaac Sim 6.2.0 arm64 image exists; not tested |
| P6.4 | ✅ | MuJoCo Playground 0.2.0 on dgx-2 (#48) |
| P6.5 | ✅ | MLflow on dgx-2 behind sign-in (#52, #95); Isaac Lab and MuJoCo runs log to it (#66). A policy video is still to do |
| P6.1, P6.6–P6.12 | ⬜ | |

### Still to do from the DGXMM/LiteLLM session list
- Done 2026-11-15: P0.14, P0.7 dead routes, P2.4, P2.6 (LiteLLM), P1.11 judge, the skill-scanner judge on both Jetson
  users, the LiteLLM admin UI and DGXMM UI sign-in.
- picoclaw end-to-end reply over NATS, and the Hermes chat tests (both profiles). Both agents now have motion tools
  (through the governor), so run these with you present or the tools disabled.
- Open WebUI sign-in (P1.13), after you give the family list.
- P2.0 models and aliases (you), then P2.1–P2.3, P2.5, P2.7, P2.8.

### Findings to report upstream
Drafts in `docs/upstream-issues/` (8, not posted; post them yourself or ask).
- Edge Connector 1.0.9 doesn't build against mbedTLS 3.6 (deprecated API + -Werror).
- `cisco-ai-mcp-scanner` 4.8.7 pins `litellm==1.93.2` (GHSA-7hp6-4w63-5g45).
- DefenseClaw's Hermes connector supports one HERMES_HOME; a second profile stops the gateway from starting (worked around with one Linux user per profile).
- OSS Fleet gateway denies every escalated tool hash and has no allow API (`sidecar.go` default-deny pipeline).
- Edge Connector C tool table lacks picoclaw's `message`, `i2c`, `serial`, `spawn`, `cron`; `picoclaw_hook.py` is FFI-only and never uses the daemon socket.
- Fleet gateway's MQTT client is MQTT 5 only (paho.golang) while the C devices speak 3.1.1; docs say 3.1.1 for both.
- `defenseclaw policy edit scanner -p` writes lowercase severity keys next to the preset's uppercase ones.

## 3. Phase 0: Urgent fixes (week 1)

| ID | Task | Depends | Effort | Acceptance |
|---|---|---|---|---|
| P0.1 | Finish the Pi backup; check it with `zstd -t` | — | 0.5 | Archive tests OK; listing has picoclaw, `.defenseclaw`, mamba env, maps, Tailscale state |
| P0.2 | Pi on the 1 TB card: boot the new OS; restore Tailscale identity, picoclaw + config + hook, ROS (mamba) env, maps, mosquitto-certs, fleet-metrics, dclaw-tunnel, units (no vision); headless | P0.1 | 2 | Same Tailscale node `100.64.25.22`; `picoclaw gateway` running; root filesystem ~1 TB |
| P0.3 | DefenseClaw 1.0.9 on the Jetson: managed gateway as a restarting system service; Hermes hook for tool calls fails closed; fix the `web` skill's missing `SKILL.md` | — | 1 | `defenseclaw-gateway status` healthy after a reboot; a test tool call while the gateway is stopped is **blocked** |
| P0.4 | DefenseClaw **Edge Connector** 1.0.9 on the Pi for picoclaw (strict, local decisions); until NATS exists (P1.5), keep the current SSH tunnel to the Jetson gateway as the upstream | P0.2, P0.3 | 1 | With the upstream unreachable, a robot tool call is still decided locally; logs show the verdict |
| P0.5 | DefenseClaw on dgx-1: upgrade managed 1.0.2 → 1.0.9 | — | 0.5 | `--version` shows 1.0.9; hook-guardian healthy |
| P0.6 | Bind LiteLLM Postgres and Redis to localhost / the Docker network | — | 0.5 | `ss -tln` shows no `0.0.0.0:5432` or `:6379`; LiteLLM still serves |
| P0.7 | Remove dead LiteLLM routes (`qwen3.6-35b`, `whisper-large-v3-turbo`) and the `nginx-gateway` container | — | 0.5 | `/model/info` lists only live routes; no restarting containers |
| P0.8 | Move the LiveKit keys out of the command line into a config file (mode 0600) | — | 0.5 | `ps` shows no secret |
| P0.9 | IP reservations for all devices; fix `pi.nghodki.ai`; picoclaw's MQTT broker → a name (broker arrives in P1.5) | — | 0.5 | Names resolve after a reboot of the router |
| P0.10 | Tailscale back on Omarchy; Omarchy reachable by name | — | 0.5 | `tailscale status` shows it online |
| P0.11 | Sparks on Ethernet (10 GbE ports) | cables | 0.5 | `ip -br addr` shows Ethernet up; Wi-Fi is a fallback |
| P0.13 | Pin LiteLLM to a tested release (today `main-latest` = 1.100.0; latest v1.109.1) | — | 0.5 | `docker inspect` shows a fixed tag or digest; all routes still work |
| P0.12 | Fix or remove the Jetson's `companion-agent.service` | — | 0.25 | No failing units |

**Exit (M0):** F1–F8 and F10 closed (F9 handled by P0.2 and the SSD purchase).

## 4. Phase 1: Foundation (weeks 2–3)

| ID | Task | Depends | Effort | Acceptance |
|---|---|---|---|---|
| P1.1 | Create the private repo `github.com/nikghodki/homelab`; push the docs; set up the layout (`hosts/ cluster/ models/ agents/ tools/ policies/ robots/ secrets/ runbooks/ decisions/`) | — | 0.5 | Repo exists; commits use the nikghodki noreply identity |
| P1.2 | SOPS + age: generate the key, store it offline + in the password manager, `.sops.yaml` | P1.1 | 0.5 | A test secret decrypts on dgx-1, not in CI |
| P1.3 | Ansible inventory and roles for dgx-1, dgx-2, Jetson, Omarchy, Pi: base hardening, Tailscale, unattended security upgrades, OTel collector, Lynis | P1.1 | 3 | `ansible-playbook --check` is clean on all 5 hosts |
| P1.4 | Tailscale tags and ACL (architecture §4.2) as `policies/tailscale.hujson` | P1.1 | 1 | The Pi can't reach LiteLLM directly; the admin Mac can SSH everywhere |
| P1.5 | NATS JetStream (Docker on dgx-1/dgx-2 for now) with MQTT; accounts for picoclaw and HA; picoclaw's `allow_from` set | P0.9 | 2 | picoclaw connects via MQTT with its own account; an anonymous publish is refused |
| P1.6 | Observability on dgx-2: VictoriaMetrics, Loki, Tempo, Grafana (+ **all 19 DefenseClaw dashboards** and its alert rules in vmalert), collectors on all hosts, dcgm-exporter (Sparks), jetson-stats exporter | P1.3 | 3 | Fleet board shows all 5 hosts; DefenseClaw Overview shows Hermes hook calls |
| P1.7 | Alerts: vmalert rules (architecture §15.4 and the operations thresholds), Gatus checks (including every DefenseClaw gateway), alert routing → Hermes + **ntfy** | P1.6 | 1.5 | Stopping a gateway pages both channels within 2 min |
| P1.8 | GitHub Actions: `pr-checks.yml`, `nightly-scan.yml`, Renovate; actions pinned by SHA; read-only token | P1.1 | 2 | A PR with a fake secret fails gitleaks; Renovate opens a PR |
| P1.9 | Decide on GitHub Pro (enforced checks) | — | — | Decision recorded in `decisions/` |
| P1.11 | DefenseClaw everywhere, phase 1: AI discovery on every host; nightly `defenseclaw aibom scan --json` per host stored on dgx-2 and diffed (morning digest); DefenseClaw webhooks → alert router; LLM judge pointed at LiteLLM (`DEFENSECLAW_LLM_KEY`); `policies/defenseclaw/` in Git with the rulepack check in CI; CI job that refreshes dashboards and rules from each DefenseClaw release | P0.3, P0.5, P1.6, P1.7 | 3 | The AI Agent Usage & Detection dashboard lists every agent, model server and MCP server on all hosts; a new MCP server shows up in the next digest |
| P1.12 | Edge Connector Fleet escalation: DefenseClaw Fleet gateway on dgx-1; picoclaw's Edge Connector escalates over MQTT through NATS; signed policy updates over MQTT; retire the SSH tunnel to the Jetson | P1.5, P0.4 | 1.5 | An undecided call from the Pi is decided by the Fleet gateway; a signed policy update reaches the Pi and rolls back on failure |
| P1.13 | **Pocket ID** (passkey sign-in) + oauth2-proxy behind Caddy; Grafana, Argo CD, Open WebUI, Gatus, Phoenix and LiteLLM UI on OIDC; Home Assistant and DGXMM UI through oauth2-proxy | P1.6 | 2 | Every UI asks for your passkey once; no UI reachable without it |
| P1.14 | **One Alertmanager** for vmalert, Gatus, DefenseClaw webhooks and Kubernetes events; routes to Hermes, ntfy (and later the console) | P1.7 | 1 | A test alert from each source arrives once, grouped; acknowledging silences it everywhere |
| P1.15 | Grafana **Fleet Home** dashboard + folder structure + data links (DefenseClaw log → Loki → Tempo → Phoenix); **Homepage** launcher at `ops.nghodki.ai` | P1.6, P1.13 | 1.5 | From Fleet Home, one click reaches any detail board; the launcher shows live status for every UI |
| P1.10 | Backups: restic to dgx-2 for HA, Hermes, picoclaw (off-site target **on hold**) | P1.3 | 1 | First restore test passes |

**Exit (M1):** one place to see everything; alerts work; every change goes through the repo.

## 5. Phase 2: Model plane (weeks 4–5)

| ID | Task | Depends | Effort | Acceptance |
|---|---|---|---|---|
| P2.0 | **Decide the models and alias names** (design D4): which models serve chat, coding, robot, safety, vision, embeddings and speech; which are always on; their fallbacks. Recalculate the memory budget. | — | 1 | Decision recorded in `decisions/`; `models/` entries drafted |
| P2.1 | DGXMM on dgx-2 (same version as dgx-1), its own catalog | — | 1.5 | dgx-2 deployments visible; LiteLLM routes registered |
| P2.2 | LiteLLM aliases and fallbacks as decided in P2.0; one key and budget per agent (Hermes, picoclaw, OpenBot, workers) | P2.1 | 1.5 | Stopping `smart` on dgx-1 → requests served by the dgx-2 copy or `fast`; per-agent spend visible |
| P2.3 | Always-on robot and safety models (per P2.0); picoclaw → the robot alias | P2.2 | 1 | p95 for the robot alias < 1 s while the main chat model is busy (measured) |
| P2.4 | Build the **DefenseClaw guardrail plugin for LiteLLM**: a custom LiteLLM guardrail (pre-call, post-call, `pre_mcp_call`) that uses DefenseClaw's **agent-gateway route**; fail closed for tool calls; tests | P2.3 | 2 | A known prompt injection is blocked at LiteLLM for an agent without hooks; with DefenseClaw stopped, an MCP tool call is refused |
| P2.5 | ModelScan/picklescan in DGXMM's download step; approval for remote-code models | P2.1 | 1 | A test pickle with code is refused |
| P2.6 | Phoenix on dgx-2; LiteLLM and agents send OTLP traces | P1.6 | 1 | One Hermes conversation is visible end to end with token counts |
| P2.7 | DGXMM memory reserves: dgx-1 ≥ 8 GiB free; dgx-2 15–23 GiB for services | P2.1 | 0.5 | Decider refuses a plan that breaks the reserve |
| P2.8 | DGXMM auto-registers and removes LiteLLM routes (no stale routes) | P2.1 | 1 | Removing a deployment removes its route |

**Exit (M2):** every agent uses aliases; the robot has its own always-on model; every model call is guarded and
traced.

## 6. Phase 3: Cluster and GitOps (weeks 6–7)

| ID | Task | Depends | Effort | Acceptance |
|---|---|---|---|---|
| P3.1 | ~~Confirm D2 (etcd-only member on the Jetson)~~ | — | — | **Done 2026-11-14: confirmed** |
| P3.2 | k3s servers on dgx-1 and dgx-2 (embedded etcd); etcd-only member on the Jetson; Omarchy as an agent node; labels and taints | P3.1, P0.11 | 2 | `etcdctl member list` shows 3; rebooting either Spark keeps the API up |
| P3.3 | kube-vip floating IP; move DNS + HTTPS proxy into the cluster (2 replicas); `*.nghodki.ai` → floating IP | P3.2 | 1.5 | Rebooting dgx-1: names keep resolving, the proxy keeps serving |
| P3.4 | Argo CD (pulls the repo, read-only deploy key); SOPS decryption in-cluster | P3.2, P1.2 | 1.5 | A merge to `cluster/` deploys without manual steps |
| P3.5 | Kyverno (signed images, no privileged pods except an allowlist, limits, no `latest`); `build-sign.yml` with cosign keyless | P3.4, P1.8 | 2 | An unsigned image is rejected; a signed one runs |
| P3.6 | **Tetragon** on the Sparks, the Jetson and Omarchy with DefenseClaw kernel controls (Plane C): observe first, then enforce ring by ring; kernel-control panels and alerts live | P3.2, P1.11 | 2 | A blocked open by an agent process shows on the Runtime Planes dashboard; the kernel-denial alert fires |
| P3.7 | Move into the cluster: LiteLLM (2 replicas), NATS (3), Postgres (CNPG: primary dgx-2, standby dgx-1), observability stack, Gatus, ntfy, Open WebUI | P3.4 | 3 | Each runs from Git; the old Docker copies are removed |
| P3.8 | etcd snapshots and CNPG backups to SeaweedFS on dgx-2 | P3.7 | 1 | Restore test: a deleted namespace is recovered from backup |
| P3.9 | Operations runbooks in `runbooks/` (architecture §17.2) | P3.7 | 1.5 | Each runbook walked through once |

**Exit (M3):** any single machine can reboot without an outage; deployments come only from Git.

## 7. Phase 4: Agents, tools, OpenBot (weeks 8–10)

| ID | Task | Depends | Effort | Acceptance |
|---|---|---|---|---|
| P4.1 | OpenBot = **CopilotKit/OpenBot** (decided 2026-11-14). Settle the CopilotKit Intelligence licensing path on Linux (managed service or self-hosted license) | — | 0.5 | Path chosen and written in `decisions/` |
| P4.2 | **LiteLLM MCP gateway:** register the MCP servers (HA, robot, ros.nav, code sandbox, jobs, search); generate each agent key's MCP access groups and tool permissions from `agents/*/scopes.yaml`; `pre_mcp_call` approvals via Hermes/ntfy (60 s, default no); same `LITELLM_SALT_KEY` on both replicas; MCP calls traced to Phoenix | P2.4, P3.7 | 2.5 | An out-of-scope tool call is refused; a physical action waits for approval; the call appears in Phoenix with the agent's identity |
| P4.3 | MCP admission: DefenseClaw admission scanning (`asset_policy` in Git) and registries subscriptions; mcp-scanner (static) in CI before a server is registered in LiteLLM; live rescan at home nightly; nightly comparison of tool descriptions with approved hashes in `tools/` (LiteLLM doesn't do this) | P4.2, P1.8 | 1.5 | Changing a tool description removes the tool from agents' permissions until it is re-approved |
| P4.4 | Agent contract: generator for the LiteLLM key (models + MCP tools + A2A peers), NATS user and Postgres schema from `agents/<name>/`; `ops agent-freeze` | P4.2 | 2 | Creating an agent folder provisions all three; freeze revokes all three |
| P4.5 | Hermes into the contract (key, scopes, A2A, memory, traces); its MCP tools (Home Assistant, wedding) move behind LiteLLM | P4.4, P4.2 | 1.5 | Hermes uses HA through LiteLLM and delegates a task to a worker via A2A |
| P4.6 | CopilotKit OpenBot on Omarchy (Docker, Bun 1.4+, run from source or Helm on the amd64 node): supervisor, one computer per bot, `COMPUTER_RUNTIME=runsc` (gVisor), per-bot egress policy, `OPENAI_BASE_URL` → LiteLLM with OpenBot's own key, DefenseClaw managed on the host and its **agent-gateway route** called from OpenBot's policy gateway, OTLP to Phoenix, weekly rebuild | P4.1, P4.4 | 3 | A bot finishes a browser task in its own computer; an off-allowlist site is blocked; OpenBot's audit and DefenseClaw both log every action; live view and take-over work |
| P4.7 | Temporal on dgx-2; worker agents on Omarchy | P3.7 | 2 | A workflow survives an Omarchy reboot and resumes |
| P4.8 | Self-hosted ARC runner on dgx-2 (private repo only, LiteLLM-only network policy); `redteam.yml`: promptfoo on change, garak weekly, PyRIT monthly | P2.2, P3.4 | 2 | Weekly garak report appears in Actions |
| P4.10 | **LiteLLM A2A pilot:** register Hermes, OpenBot and one worker as A2A agents; per-key allowed peers; traces | P4.4 | 1.5 | Hermes → OpenBot delegation works through LiteLLM and is refused for a key without that peer |
| P4.11 | **Fleet Console UI/UX design** (pages, layout, interactions), then build the read-only version: overview, alerts, approvals, agents, models, tools, security, robot, deploys | P4.4, P1.13, P1.14 | 1 (design) + 5 (build) | Design agreed; read-only console shows live data from every source behind Pocket ID |
| P4.12 | Fleet Console actions: approve/deny, freeze agent, quarantine host, e-stop, load/unload model, roll back; each checked by DefenseClaw and audited | P4.11, P4.2 | 3 | Each action works end to end and appears in the audit log |
| P4.13 | "Ask the fleet" chat: ops agent with read-only MCP tools (Grafana MCP, Argo CD, Kubernetes, DGXMM, DefenseClaw) | P4.11 | 1.5 | Answers questions with links to the data it used; write requests become approvals |
| P4.9 | a2a-scanner and Agentic Radar in CI for `agents/` | P1.8 | 1 | A test agent card with an unsafe capability fails CI |

**Exit (M4):** every agent follows the contract; OpenBot has its own safe computer; red-team runs automatically.

## 8. Phase 5: Robotics (weeks 10–12)

| ID | Task | Depends | Effort | Acceptance |
|---|---|---|---|---|
| P5.1 | ROS 2 on the Jetson (JetPack 7) and the Pi (from the restored mamba env, or apt); `rmw_zenoh`; Zenoh router on the Jetson | P0.2 | 3 | `ros2 topic hz /scan` on the Jetson shows the Pi's LiDAR |
| P5.2 | Safety governor on the Pi: e-stop, speed caps, obstacle stop, 2 s heartbeat watchdog; `robot.pi.safety.estop` | P5.1, P1.5 | 2 | All four tests pass with the robot on blocks |
| P5.3 | SLAM + Nav2 on the Jetson; maps in Git | P5.1 | 3 | Robot navigates to a named spot |
| P5.4 | Nav2 bridge: `robot.<id>.cmd.goal` → Nav2; telemetry back to NATS | P5.3 | 1.5 | A goal published on NATS moves the robot |
| P5.5 | picoclaw `robot.*` tools registered in the LiteLLM MCP gateway with approval rules | P4.2, P5.4 | 1 | Hermes → robot goal end to end, approved on WhatsApp |
| P5.6 | Rosbags streamed to dgx-2 (30-day retention); Foxglove for live view | P5.1 | 1 | A run's bag appears on dgx-2 |
| P5.7 | Robot board in Grafana; heartbeat and battery alerts | P1.6 | 0.5 | Unplugging Wi-Fi alerts and the robot stops |

**Exit (M5):** "Hermes, send the robot to the kitchen" works end to end, safely.

## 8a. Phase 6: Simulation and robot learning (weeks 9–16)

| ID | Task | Depends | Effort | Acceptance |
|---|---|---|---|---|
| P6.1 | Robot description: measure the Pi robot (dimensions, masses, wheels, sensor poses); one source in `robots/models/` converted to URDF, MJCF and USD; LiDAR and camera sensor models | — | 3 | The same scripted drive gives matching paths in both simulators and close to a real rosbag |
| P6.2 | Isaac Lab 3.0 on dgx-2 (uv, aarch64 path, headless Newton), as a pinned container | P2.7 | 1.5 | Cartpole and a wheeled-robot example train headless; memory within budget |
| P6.3 | Isaac Sim (a version Isaac Lab 3.0 supports) on dgx-2 for RTX camera/LiDAR rendering; headless | P6.2 | 1.5 | A camera and LiDAR render of the robot scene is saved; GB10 support confirmed |
| P6.4 | MuJoCo + MuJoCo Playground (MJX) or MuJoCo Warp on dgx-2, pinned container | P2.7 | 1 | A Playground locomotion example trains on the GB10 GPU |
| P6.5 | MLflow on dgx-2 (CNPG Postgres + SeaweedFS artifacts), behind sign-in | P3.7 | 1 | A training run logs metrics, a video and a model version |
| P6.6 | Sim jobs in the GPU queue with memory footprints; DGXMM budget covers them; `jobs.submit` MCP tool in LiteLLM (approval required); Temporal workflow train → eval → export → register → PR | P4.2, P4.7, P6.5 | 2.5 | A job submitted by the robot-learning agent waits for approval, runs within the budget and opens a PR |
| P6.7 | First task: navigate to a named spot while avoiding obstacles, using LiDAR, in Isaac Lab with domain randomization; cross-check in MuJoCo | P6.1–P6.4 | 4 | ≥ 95% success and 0 collisions over the fixed eval set in **both** simulators |
| P6.8 | Export: ONNX → TensorRT (Jetson) and ONNX Runtime (Pi); output-equivalence test; `robots/policies/<name>.yaml` | P6.7 | 1.5 | Exported model matches the original within tolerance; runs at the control rate on the target |
| P6.9 | Real-world gates: shadow mode → on blocks (safety-governor tests) → 25% speed canary in a fenced area → live; one-PR rollback | P5.2, P6.8 | 2 | Each gate passes and is recorded in the PR |
| P6.10 | CI: MuJoCo smoke eval on every policy PR (self-hosted runner); nightly Isaac Lab eval suite; results in MLflow | P4.8, P6.7 | 1 | A policy PR that regresses fails CI |
| P6.11 | Real-to-sim loop: rosbags → datasets in SeaweedFS → calibrate the simulation (friction, latency, sensor noise) | P5.6, P6.7 | 2 | A calibrated simulation reduces the sim-vs-real path error on a replayed run |
| P6.12 | Security: scan the NGC and simulator images (Trivy in CI); sim jobs have no internet egress except approved model and asset downloads; agent-written reward/env code runs only in sandboxed job containers | P3.5 | 1 | An unscanned image is refused; a sim job can't reach the internet |

**Exit (M6):** a policy trained in simulation passes both simulators' evals and every real-world gate, and runs
on the robot under the safety governor.

## 9. Optional: KServe pilot (parallel, from week 6)

| ID | Task | Depends | Effort | Acceptance |
|---|---|---|---|---|
| PK.1 | Install KServe (RawDeployment) on k3s; confirm arm64 images and the deployment-mode annotation | P3.2 | 1 | KServe controller healthy on a Spark |
| PK.2 | Advertise `nghodki.ai/unified-mem-gib`; GPU time-slicing in the device plugin | PK.1 | 1 | Two engines scheduled on one Spark within the memory limit |
| PK.3 | Wire `KServeController` into DGXMM (`backend: kserve` setting, `base_url` via backend, `pods/exec` Role); test secret delivery | PK.2 | 2 | `robot-fast` and `guard` run as InferenceServices under DGXMM |
| PK.4 | Run both backends side by side for 2 weeks; decide | PK.3 | — | Decision recorded |

## 10. Purchases

| Item | Why | Approx. cost | Needed by |
|---|---|---|---|
| UPS (~1000–1500 VA) for both Sparks, the switch and the router | Power cuts (R10) | $150–250 | Phase 1 |
| SATA SSD (500 GB–1 TB) for the Inspiron | Container pulls and desktops are disk-bound (R5) | $30–60 | Phase 4 |
| Ethernet cables (and a switch port) for both Sparks | P0.11 | $10–40 | Phase 0 |
| GitHub Pro (optional) | Enforced required checks (R8) | $4/month | Phase 1 decision |
| Off-site backup (USB drive or B2) | 3-2-1 | $0–5/month | Phase 1 |

## 11. Risks

See design §10 (R1–R10). Plan-specific risks:

| Risk | Impact | Mitigation |
|---|---|---|
| Restoring the Pi from a running-system backup misses something | Robot functions broken | Old 32 GB card kept untouched as a fallback |
| ROS 2 on JetPack 7 / Debian 13 has packaging gaps | Phase 5 slips | Use the mamba (RoboStack) env that already works on the Pi; containers on the Jetson |
| CopilotKit Intelligence licensing on Linux (R11) | Phase 4 slips | Settle it in P4.1; fallback trycua/cua desktop + OpenShell |
| Moving services into k3s breaks something you rely on (Open WebUI, Coolify apps) | Outage | Move one service at a time; keep the Docker copy until the new one is verified |
| Free Actions minutes run out | CI stops | Move long jobs to the self-hosted runner; watch the billing page |
| Isaac Sim version or features on GB10 don't match the docs (R13) | Camera/LiDAR rendering delayed | Train first with Newton (no rendering) and MuJoCo; add Isaac Sim rendering when confirmed |
| Robot description inaccurate | Policies don't transfer | P6.1 acceptance compares against a real rosbag; P6.11 calibration |

## 12. Decisions still open

| # | Question | Needed by |
|---|---|---|
| 0 | Models and alias names (D4) | P2.0 |
| 0a | Fleet Console UI/UX design | P4.11 |
| 2 | Backups on, and the off-site target (**off/on hold**, decisions/0002) | P1.10 |
| 3 | CopilotKit Intelligence licensing path | P4.1 |
| 4 | When to bring back vision | after M5 |

Decided 2026-11-14: etcd-only member on the Jetson (D2); OpenBot = CopilotKit/OpenBot (D13); Pocket ID (D22); standalone Fleet Console (D23).

## 13. Tracking

- Each task becomes a GitHub issue in `nikghodki/homelab`, with a label per phase (`phase-0` … `phase-5`, `kserve`).
- PRs reference their issue.
- Decisions go in `decisions/NNNN-title.md`.
- This plan is updated at the end of each phase.
