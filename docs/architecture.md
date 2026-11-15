# Home AI Fleet: Architecture

| | |
|---|---|
| Owner | nikghodki |
| Status | Draft v1.1, 2026-11-15 |
| Related | [design.md](design.md) (requirements and decisions D1–D25), [project-plan.md](project-plan.md) |

Numbers marked "est." are estimates, not measurements.

**Changes 2026-11-15** (k3s layout, Phase 3, brought in line with what is built and decided):
- The Jetson is an etcd member **plus a tainted worker** for robot, home and agent pods (D2 updated). §3, §5.
- k3s, etcd and CNI traffic between the Sparks uses the direct link `10.100.136.0/24`. §4.4.
- Placement of the Fleet MQTT broker and API proxy, dcgm-exporter, Pocket ID and the web CA cert. §3.1, §4.5.
- New: what stays outside k3s (§3.2) and the interim Docker deployments with their k3s targets (§3.3).
- Edge Connector escalation goes through the dedicated Fleet broker (D24), not NATS MQTT. §12.2.

---

## 1. System context

```
   You (WhatsApp, phone, browser)          GitHub (nikghodki/homelab, Actions)        Internet (HF, APIs)
          │                                      ▲ PRs, CI          │ pull                 ▲ egress via
          │ Tailscale / WhatsApp                 │                  ▼                      │ allowlists
   ┌──────▼──────────────────────────────────────┴──────────────────────────────────────────┴──────┐
   │                                HOME AI FLEET                                                  │
   │  dgx-1 · dgx-2 · Jetson · Omarchy · Pi      (LAN + Tailscale + 200G Spark link)               │
   │  models · agents · tools · home · robot · security · observability                            │
   └───────────────────────────────────────────────────────────────────────────────────────────────┘
          │                                                     │
          ▼                                                     ▼
   ntfy (backup alert channel)                          Off-site backup (USB drive or B2)
```

## 2. Layers

```
╔═══════════════════════════════════════════════════════════════════════════════════════════════╗
║ ACCESS       WhatsApp (Hermes) · Open WebUI · Grafana · Phoenix · DGXMM UI · Foxglove         ║
╠═══════════════════════════════════════════════════════════════════════════════════════════════╣
║ CONTROL      k3s (servers: dgx-1, dgx-2; etcd+edge: Jetson) · kube-vip floating IP · Argo CD  ║
║ PLANE        DNS + HTTPS proxy · NATS JetStream (+MQTT) · Postgres · SOPS · Kyverno           ║
╠═══════════════════╦═══════════════════════╦══════════════════════╦════════════════════════════╣
║ MODEL PLANE       ║ TOOL PLANE            ║ AGENT PLANE          ║ JOB PLANE                  ║
║ LiteLLM (aliases, ║ LiteLLM MCP + A2A     ║ Hermes · OpenBot ·   ║ Temporal · GPU batch queue ║
║ keys, budgets)    ║ tool perms · approvals║ picoclaw · workers · ║ self-hosted CI runner      ║
║ DefenseClaw       ║ DefenseClaw · audit   ║ coding agents        ║ (red-team)                 ║
║ guardrail → DGXMM ║                       ║                      ║                            ║
╠═══════════════════╩═══════════════════════╩══════════════════════╩════════════════════════════╣
║ ROBOTICS     Pi (drivers, safety, reflexes) ⇄ Zenoh ⇄ Jetson (SLAM, Nav2) ⇄ bus ⇄ DGX (VLM)    ║
╠═══════════════════════════════════════════════════════════════════════════════════════════════╣
║ SECURITY     DefenseClaw · guard models · Kyverno · Tetragon · CrowdSec · scanners in CI      ║
║ OBSERVE      OTel Collector per host → VictoriaMetrics · Loki · Tempo → Grafana; Phoenix; Gatus║
╠═══════════════════════════════════════════════════════════════════════════════════════════════╣
║ UNDERLAY     LAN (Sparks on Ethernet) · Tailscale (tags, MagicDNS, SSH) · 2×200G RDMA         ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════╝
```

## 3. Deployment view (what runs where)

```
┌──────────────── dgx-1 (k3s server) ─────────────────┐ ┌──────────────── dgx-2 (k3s server) ─────────────────┐
│ DGXMM (owns GPU): robot-fast, guard, embed, stt,    │ │ DGXMM (owns GPU): batch, evals, fine-tune, Isaac    │
│   tts (always on); smart, vision, coder (on demand) │ │   Lab/Sim, MuJoCo; fallback smart, robot-fast       │
│ LiteLLM replica · DefenseClaw guardrail plugin      │ │ LiteLLM replica · Postgres primary (CNPG)           │
│ NATS · DNS + proxy replica · Open WebUI · Coolify   │ │ NATS · DNS + proxy replica · Argo CD · Temporal     │
│ Postgres standby · OTel Collector · Tetragon        │ │ VictoriaMetrics · Loki · Tempo · Grafana · Phoenix  │
│ DefenseClaw managed + Fleet gateway (host)          │ │ Gatus · ntfy · SeaweedFS · MLflow · Pocket ID       │
│ Fleet broker (Mosquitto) + API proxy · dcgm-exp.    │ │ ARC runner · OTel · Tetragon · restic · dcgm-exp.   │
└───────────────────────┬─────────────────────────────┘ └──────────────────────┬──────────────────────────────┘
                        └── 2×200G: k3s/etcd/CNI, pooled models, model sync ───┘
┌──────── Jetson (etcd + tainted agent) ─────┐ ┌──────── Omarchy (agent, x86) ──────────┐ ┌──── Pi (Ansible) ──────┐
│ etcd member; worker tainted for robot pods │ │ OpenBot + its sandboxed computer       │ │ ROS 2 drivers: LiDAR,  │
│ Hermes + DefenseClaw (host until P4.5)     │ │  (container desktop, gVisor/OpenShell, │ │  camera, motors        │
│ Home Assistant · LiveKit                   │ │  egress allowlist), one at a time      │ │ safety governor        │
│ Nav2 · SLAM · Zenoh router · Nav2 bridge   │ │ light worker agents                    │ │ picoclaw + DefenseClaw │
│ OTel Collector · Tetragon · headless       │ │ DefenseClaw managed · OTel · Tetragon  │ │  Edge Connector        │
└────────────────────────────────────────────┘ └────────────────────────────────────────┘ │ Zenoh · collector      │
                                                                                         └────────────────────────┘
```

### 3.1 Namespaces

| Namespace | Contents | Runs on |
|---|---|---|
| `edge` | DNS (CoreDNS for `*.nghodki.ai`), HTTPS proxy (Caddy, wildcard cert from a Secret, §4.5), `ca.nghodki.ai` install page, CrowdSec | Sparks (2 replicas) |
| `bus` | NATS JetStream (3 replicas: dgx-1, dgx-2 and, as a small replica, the Jetson) | Sparks + Jetson (tolerates the taint) |
| `models` | LiteLLM (model, MCP and A2A gateway), DGXMM (one per Spark), DefenseClaw guardrail plugin | Sparks |
| `data` | CloudNativePG Postgres, SeaweedFS | Sparks |
| `agents` | Hermes (after P4.5), OpenBot, workers; MCP servers that run in the cluster | Omarchy, Sparks; Hermes on the Jetson |
| `home` | Home Assistant, LiveKit | Jetson (tolerates the taint) |
| `robot` | Nav2 bridge, Zenoh router (host network) | Jetson (tolerates the taint) |
| `jobs` | Temporal, batch jobs, ARC runners | dgx-2 |
| `sim` | Isaac Lab / Isaac Sim and MuJoCo training and evaluation jobs, MLflow | dgx-2 (dgx-1 overnight) |
| `observe` | VictoriaMetrics, Loki, Tempo, Grafana, Phoenix, Gatus, Alertmanager, ntfy, OTel gateway; **dcgm-exporter** (DaemonSet, `role=gpu` nodes only) | dgx-2; dcgm-exporter on both Sparks |
| `console` | Fleet Console, Homepage (interim), **Pocket ID** (`id.nghodki.ai`), oauth2-proxy | dgx-2 |
| `security` | Kyverno, Tetragon, policy bundles, nightly AIBOM job; **Fleet MQTT broker** (Mosquitto, D24, `fleet.nghodki.ai:8884`, TLS, per-device ACLs); **Fleet API TLS proxy** (Caddy `:8971`) | Fleet broker and proxy pinned to dgx-1 |
| `argocd` | Argo CD | Sparks |

- **Fleet API proxy.** The DefenseClaw Fleet gateway is part of the host-installed DefenseClaw on dgx-1 and listens
  on loopback. The proxy must reach it over loopback, so it runs as a `hostNetwork` pod pinned to dgx-1 and forwards
  only `/api/v1/fleet/*`. If the gateway ever runs as a pod, the proxy becomes a sidecar in that pod instead.
- **Fleet broker.** Mosquitto keeps its own TLS certificate from the internal homelab CA (§4.5) and its per-device
  ACLs and passwords as Secrets from SOPS. Port 8884 is a `LoadBalancer`/host port on dgx-1, because the Pi (not a
  node) connects to it.
- **dcgm-exporter** keeps listening on loopback `:9400`; the host OTel collector scrapes it as today. It needs the
  NVIDIA device plugin / CDI on the Sparks.

### 3.2 Outside k3s (Ansible-managed on the hosts)

| What | Where | Why |
|---|---|---|
| Per-user DefenseClaw installs (gateway, hook connectors, Fleet gateway, sensor) | every host | They guard host processes and hooks, and must work when the cluster is down |
| Host OTel collectors and fleet-metrics | every host | Host metrics and journald; the observability path must not depend on the cluster |
| Tailscale | every host | Underlay; the cluster depends on it, not the other way round |
| CA trust stores (internal homelab CA and web CA, role `homelab_ca`) | every host | Host trust is needed before any pod can pull or talk TLS |
| picoclaw, Edge Connector daemon, ROS 2 drivers, safety governor | Pi | The Pi isn't a node |
| OpenBot's per-bot computers (Docker, gVisor `runsc`) | Omarchy | Created and destroyed by OpenBot's supervisor, not by Kubernetes |
| Model engines (vLLM, llama.cpp) | Sparks | Started by DGXMM as Docker containers (D3). They move into k3s only if the optional KServe pilot (PK.*) succeeds |
| Hermes, DefenseClaw gateway | Jetson | Host-installed until P4.5 moves Hermes into `agents` |

### 3.3 Interim deployments (Docker on hosts, before k3s)

These run today as Docker Compose stacks, deployed by Ansible (`hosts/playbooks/<name>.yml`, `hosts/stacks/<name>/`)
unless noted. P3.7 moves each into its k3s namespace and removes the Docker copy.

| Stack | Host | Contents | k3s target |
|---|---|---|---|
| `observe` | dgx-2 | VictoriaMetrics, vmalert, Alertmanager, Loki, Tempo, two OTel gateways, Grafana, Gatus, ntfy, Phoenix | `observe` |
| `console` | dgx-2 | Pocket ID 2.19.2 (LAN port 1411; dgx-1 Caddy terminates TLS) | `console` |
| `bus` | dgx-1 | NATS 2.15.3 (4222 TLS, MQTT 8883 TLS) | `bus` (3 replicas) |
| `fleet` | dgx-1 | Mosquitto 2.1.2 (8884 TLS), Caddy Fleet API proxy (host network, `:8971`) | `security` |
| `gpu` | dgx-1, dgx-2 | dcgm-exporter (loopback 9400) | `observe` (DaemonSet) |
| `backup` | dgx-2 | restic rest-server (8000) | Stays on the host (restores must not need the cluster) |
| edge-gateway | dgx-1 | `edge-caddy` + `edge-dnsmasq` in `~/edge-gateway`, **not in the repo yet** | `edge` (CoreDNS + Caddy, 2 replicas, behind kube-vip) |
| LiteLLM | dgx-1 | `litellm-proxy` v1.109.1 + Postgres + Redis (hand-run, not in the repo) | `models` (2 replicas); Postgres → `data` (CNPG); Redis → `models` |
| Open WebUI | dgx-1 | `open-webui` v0.13.3 (hand-run, not in the repo) | `agents` or `models` (decide in P3.7) |

Not moved: DGXMM and its engines (§3.2). Coolify stays a host app.

## 4. Network

### 4.1 Addressing and names
- Every device has an **IP reservation** on the router.
- Every device is reached by **Tailscale MagicDNS** name.
- `*.nghodki.ai` resolves to the **kube-vip floating IP**, which lives on whichever server is up. Tailscale split
  DNS points there. Until P3.3, `edge-dnsmasq` on dgx-1 resolves the names to dgx-1 (.44).

| Name | Service |
|---|---|
| `model.nghodki.ai` | LiteLLM |
| `webui` | Open WebUI |
| `dgxmanager` | DGXMM |
| `grafana` | Grafana |
| `phoenix` | Phoenix |
| `status` | Gatus |
| `argocd` | Argo CD |
| `ha` | Home Assistant |
| `ntfy` | ntfy |
| `id` | Pocket ID |
| `ca` | Web CA install page (http) |
| `fleet` | DefenseClaw Fleet: MQTT `:8884`, API `:8971` (dgx-1) |

### 4.2 Tailscale tags and ACLs

| Tag | Members | May reach |
|---|---|---|
| `tag:admin` | Work Mac | everything (SSH, kubectl) |
| `tag:gpu` | dgx-1, dgx-2 | each other; `tag:control` services |
| `tag:control` | dgx-1, dgx-2, Jetson (k3s ports) | each other |
| `tag:agent` | Omarchy, Jetson | LiteLLM, LiteLLM MCP gateway, NATS, Phoenix (OTLP) |
| `tag:robot` | Pi | NATS (its own subjects), Fleet broker and API on dgx-1, Zenoh router on the Jetson, the OTel collector |
| `tag:quarantine` | (applied during incidents) | `tag:admin` only |
| phone / you | your devices | the web UIs, ntfy |

### 4.3 Exposure rules
- Databases, Redis and internal APIs listen on cluster-internal addresses only (fixes F2).
- Only the HTTPS proxy, k3s, NATS, the Fleet broker and API proxy (dgx-1 `:8884`, `:8971`) and Zenoh accept
  connections from other hosts, and only from the tags above.
- No inbound connections from the internet. GitHub is reached outbound only; Argo CD pulls.

### 4.4 Links and node IPs

| Link | Addresses | Carries |
|---|---|---|
| Spark ↔ Spark, cable 1 (200 Gb/s QSFP) | `enp1s0f0np0`: dgx-1 `10.100.136.1`, dgx-2 `10.100.136.2` | k3s API, etcd peer, CNI (flannel VXLAN) between the Sparks; model sync |
| Spark ↔ Spark, cable 2 | `enP2p1s0f0np0`: `10.100.137.0/24` | RDMA for pooled models (NCCL); not used by k3s |
| LAN | Wi-Fi today on every device; the Sparks move to 10 GbE `enP7s7` to a switch in P0.11 | Everything else, including the Jetson's and Omarchy's k3s traffic |

- **Sparks:** `--node-ip=10.100.136.{1,2}`, `--node-external-ip=<LAN IP>`, `--flannel-iface=enp1s0f0np0`, and
  `--tls-san` with the LAN IPs, the kube-vip IP and the names. So etcd, the API and pod traffic between the Sparks
  use the cable.
- **Jetson and Omarchy** reach the Sparks over the LAN. They have no path to `10.100.136.0/24`, so Ansible adds
  host routes: `10.100.136.1/32 via 192.168.86.44` and `10.100.136.2/32 via 192.168.86.36`. Each Spark answers for its
  own link address on its LAN interface (`rp_filter=2`, loose, today). Their own `--node-ip` is the LAN IP.
- **MTU** is 1500 on every path today, so flannel's VXLAN MTU (1450) is the same everywhere. Raising the cable to
  jumbo frames would need the CNI MTU set by hand.
- After P0.11 the LAN path is wired, but the Spark-to-Spark traffic stays on the cable.

### 4.5 TLS and the two CAs

| CA | Scope | Used for | Trusted by |
|---|---|---|---|
| Internal homelab CA (`hosts/files/pki/homelab-ca.crt`) | No name constraint | NATS, the Fleet broker, backups, later internal service TLS | Fleet hosts only (role `homelab_ca`). **Never** installed on phones or family devices |
| Homelab web CA (`hosts/files/pki/web-ca.crt`, D25) | Name-constrained to `nghodki.ai`, `pathlen:0` | The `*.nghodki.ai` wildcard on the front door | Fleet hosts, plus your phones and computers (installed once from `ca.nghodki.ai`) |

- Both private keys live in `secrets/pki.enc.yaml` (SOPS). See `runbooks/web-https.md`.
- **In the cluster**, Argo CD decrypts the wildcard cert and key (SOPS, P3.4) into a `kubernetes.io/tls` Secret in
  `edge`. The Caddy pods mount it read-only. Renewal stays manual (397-day cert): re-issue, commit, Argo CD syncs,
  Caddy reloads.
- In-cluster services that need internal TLS (NATS, the Fleet broker) get their certs the same way, from the internal
  CA. cert-manager with a CA issuer is an option later; not needed for the first move.

## 5. Cluster

- **k3s servers:** dgx-1 and dgx-2 (API, scheduler, controllers, etcd). Node IPs on the Spark link (§4.4).
- **Jetson:** a k3s server with `--disable-apiserver --disable-controller-manager --disable-scheduler` (etcd
  member), and also a **worker** for a small set of pods. Quorum = 2 of 3 etcd members.
  - Taint `nghodki.ai/jetson=true:NoSchedule`; label `nghodki.ai/role=edge-robot`.
  - Only pods that tolerate the taint run there: `robot` (Zenoh router, Nav2 bridge), `home` (Home Assistant,
    LiveKit), the small NATS replica, and Jetson-pinned `agents` pods (Hermes after P4.5).
  - Every such pod sets tight requests and limits. `--system-reserved` keeps memory for etcd and the
    host-installed Hermes and DefenseClaw (est. 3 GiB).
  - Hermes and DefenseClaw stay host-installed until P4.5 moves Hermes.
- **Agent nodes:** Omarchy. The Pi isn't in the cluster.
- **kube-vip** gives a floating LAN IP for the API and the HTTPS proxy.
- **Node labels:**
  - `role=gpu` (Sparks)
  - `nghodki.ai/role=edge-robot` (Jetson)
  - `role=agent-x86` (Omarchy)
  - `node.kubernetes.io/instance-type=gb10|orin|x86`
- **Taints:**
  - Jetson: `nghodki.ai/jetson=true:NoSchedule` (above).
  - The Sparks take GPU-planned work and the services listed above.
- **etcd snapshots** are taken every 6 h to SeaweedFS on dgx-2, kept for 7 days.
- **Argo CD** watches `nikghodki/homelab` (read-only deploy key) and syncs `cluster/`.

## 6. Model plane

```
 agent ──"model: smart"──▶ LiteLLM (2 replicas)
                             │ per-agent key → budget, rate limit, allowed aliases
                             │ DefenseClaw guardrail plugin → DefenseClaw agent-gateway route + guard model (Prompt Guard 2 / Llama Guard / Granite Guardian)
                             ▼
                        DGXMM on dgx-1 / dgx-2  ── publishes models.<node>.status on NATS
                             │ planner: what fits where (calibrated unified-memory footprints)
                             │ decider: priorities, eviction;  on-demand: hold request, start, forward
                             ▼
                        engine (vLLM / llama.cpp) via backend:
                          DockerController (today)  |  KServeController (draft) → InferenceService
```

### 6.1 Aliases (placeholders)

The models and alias names are **not decided yet** (design D4). The table shows the kinds of capability the
fleet needs, with example names and models, so the rest of this document has something to refer to.


| Alias | Backend | Mode | Fallback |
|---|---|---|---|
| `robot-fast` | Qwen3-4B / LFM2.5 on dgx-1 | always on | dgx-2 copy |
| `guard` | Prompt Guard 2 + a small safety model on dgx-1 | always on | fail closed |
| `embed`, `stt`, `tts` | dgx-1 | always on | — |
| `smart` | qwen3.8-27b on dgx-1 | on demand | dgx-2 → `fast` |
| `coder` | qwen3-coder-30b on dgx-1/2 | on demand | `smart` |
| `vision` | VLM on dgx-1 | on demand | — |
| `big` | GLM-4.7 / DeepSeek-V4, tensor-parallel across both Sparks | pooled | `smart` |
| `batch-*` | dgx-2 queue | queued | waits |

### 6.2 Rules
- DGXMM registers and removes LiteLLM routes itself, so no route is ever left pointing at nothing (fixes F7).
- Downloads go through ModelScan/picklescan; models that require remote code need approval.
- **Priorities:** guard and robot first, then interactive, then batch.
- **Memory reserves:**
  - dgx-1 keeps ≥ 8 GiB free.
  - dgx-2 reserves 15–23 GiB for services.
- **Pooled mode:** an approved request drains dgx-2's batch work and starts the model across both Sparks over
  RDMA. Afterwards it returns both Sparks to normal.

### 6.3 LiteLLM version

LiteLLM was on `ghcr.io/berriai/litellm:main-latest` (1.100.0) until 2026-11-15; it now runs 1.109.1 pinned by digest (P0.13). Each upgrade is pinned to a tested
release (latest is v1.109.1, 2026-11-12) before it takes on MCP and A2A, and every upgrade goes through Renovate and
CI like any other image.

### 6.4 KServe backend (later)
See DGXMM `docs/architecture/kserve-backend.md` on branch `feature/kserve-backend`.

- The same `EngineBackend` contract as Docker.
- RawDeployment mode, so no Knative.
- An extended resource `nghodki.ai/unified-mem-gib` per Spark.
- Time-sliced GPU, node pinned by the planner.
- A NetworkPolicy for the internal-network engines.

## 7. Tool and agent plane (LiteLLM MCP + A2A gateway)

LiteLLM is the single gateway for models, MCP tools and agent-to-agent calls (D20). There is no separate tool
gateway.

```
 agent (own LiteLLM key) ──▶ LiteLLM
     │                         ├─ /v1/chat/completions ── models (section 6)
     │                         ├─ /mcp  ── MCP gateway ──┬─ key → allowed MCP servers and tools
     │                         │                         │   (mcp_access_groups, mcp_tool_permissions)
     │                         │                         ├─ pre_mcp_call guardrail: DefenseClaw inspect API
     │                         │                         │   + approval for physical / irreversible / money /
     │                         │                         │   messages (Hermes WhatsApp or ntfy, 60 s, default no)
     │                         │                         └─ log + OTLP trace (Phoenix), DefenseClaw audit
     │                         └─ A2A  ── agent gateway ─── key → which agents it may call
     ▼
  MCP servers:  ha.* (Jetson) · robot.* (Pi) · ros.nav (Jetson) · code.sandbox (Omarchy) ·
                jobs.submit (dgx-2) · web.search
  A2A agents:   Hermes · OpenBot · workers
```

### 7.1 How permissions are set
- `agents/<name>/scopes.yaml` in Git lists the agent's models, MCP servers, tools and A2A peers.
- CI turns it into LiteLLM key settings: allowed models, MCP access groups, tool permissions and allowed agents.
- The same key is used for all three, so one revocation (`ops agent-freeze`) cuts off models, tools and delegation
  together.

### 7.2 What LiteLLM checks on each tool call
1. **Permission:** the key must allow that server and tool.
2. **DefenseClaw:** the `pre_mcp_call` hook of the DefenseClaw guardrail plugin sends the call to DefenseClaw's
   agent-gateway route, and blocks it on a deny.
3. **Approval:** for physical, irreversible, money or messaging tools, the plugin holds the call and asks you
   (Hermes on WhatsApp, or ntfy). No answer in 60 s means no.
4. **Record:** the call is logged with the agent's identity, and traced to Phoenix under the same trace ID as the
   model calls.

The plugin is a custom LiteLLM guardrail we build (estimated a few hundred lines of Python) that uses DefenseClaw's
agent-gateway route. DefenseClaw has no LiteLLM plugin today. The agent hooks (Hermes, picoclaw, OpenBot, the coding agents) still run on top of it.

### 7.3 Admission and change detection
- A new MCP server must pass **mcp-scanner** (static, in CI) before it is registered in LiteLLM.
- A live rescan runs at home every night.
- LiteLLM doesn't notice when a server changes a tool's description after approval. A nightly job therefore
  compares every tool description with its approved hash in `tools/`, and removes the tool from the agents'
  permissions on a mismatch until you re-approve it.

### 7.4 Agent-to-agent (A2A)
- Agents register in LiteLLM as A2A agents.
- Delegation ("Hermes asks OpenBot to book a table") is an A2A call through LiteLLM, checked against the caller's
  key and traced.
- NATS remains the place for **events** ("presence changed", "job done").
- A2A support is newer in LiteLLM than MCP, so it is piloted first (project plan P4.10).

### 7.5 Robot calls
`robot.*` tools go through LiteLLM like any other tool. The robot's **safety** never depends on that path: the
Pi's safety governor and the DefenseClaw Edge Connector decide locally.

## 8. Event plane (NATS)

| Subject | Publishers | Subscribers |
|---|---|---|
| `home.presence.<person>` | Home Assistant | Hermes, automations |
| `home.device.<entity>.state` | Home Assistant | Hermes |
| `robot.<id>.telemetry.{pose,battery,heartbeat}` | Pi, Jetson | planner, Grafana |
| `robot.<id>.cmd.goal` | Hermes, planner | Nav2 bridge |
| `robot.<id>.safety.estop` | anyone authorized, your phone | Pi safety governor |
| `agents.<name>.events` | any agent | that agent (notifications; request/reply goes through LiteLLM A2A) |
| `models.<node>.status` | DGXMM | LiteLLM sync, Grafana |
| `jobs.<id>.{queued,done,failed}` | job runner | the requesting agent |
| `security.<host>.verdict` | DefenseClaw | Grafana, alerting |
| `fleet.<host>.health` | collectors | alerting |

- **One NATS account per device and agent**, allowed only its own subjects.
- MQTT clients (picoclaw, Home Assistant) connect to NATS's MQTT listener with their own accounts. This fixes F3:
  the broker address uses a name, and access is no longer open to everyone.

## 9. Agent plane

### 9.1 Agent contract

Every agent has:

| Item | Implementation |
|---|---|
| Identity | Tailscale tag, LiteLLM key (models + MCP tools + A2A peers), NATS user (all generated from `agents/<name>/`) |
| Agent card | `agents/<name>/card.yaml`, checked by a2a-scanner in CI |
| Delegation | A2A agent registered in LiteLLM; notifications on `agents.<name>.events` |
| Memory | Postgres schema `agent_<name>` (pgvector) |
| Tools | LiteLLM MCP gateway only, with the agent's own key |
| Security | A DefenseClaw connector, or else LiteLLM and the LiteLLM MCP gateway only |
| Telemetry | OTLP traces → Phoenix; logs → Loki; metrics → VictoriaMetrics |
| Kill switch | `ops agent-freeze <name>`: revoke the key, disable the NATS user, empty the scope |

### 9.2 Agents

| Agent | Host | Notes |
|---|---|---|
| Hermes | Jetson | Front door for people; delegates; WhatsApp alert and approval channel. Host-installed; a pod in `agents` after P4.5 |
| OpenBot (CopilotKit) | Omarchy | CopilotKit/OpenBot: its supervisor creates one computer per bot (Docker container with Chromium, `/workspace` and bash), with `COMPUTER_RUNTIME=runsc` (gVisor), an egress proxy with a per-bot allowlist, its policy gateway and audit log, plus DefenseClaw. Model via `OPENAI_BASE_URL` → LiteLLM (`smart`, or `coder` for coding). You can watch the screen and terminal live and take over. One computer at a time; rebuilt weekly from the image. Needs CopilotKit Intelligence. Images are amd64-only. |
| Workers | Omarchy | Scheduled and long tasks as Temporal workflows |
| picoclaw | Pi | Robot skills; accepts goals only from Hermes and the planner |
| Coding agents | dgx-1, Omarchy | Claude Code, Codex, OpenCode; OpenShell sandbox when unattended |

## 10. Robotics

| Loop | Where | What | If the link drops |
|---|---|---|---|
| < 10 ms | Pi | Motors, LiDAR driver, **safety governor** (e-stop, speed caps, obstacle stop, 2 s heartbeat watchdog) | Always local |
| 50–200 ms | Pi | Reflex skills (avoid, dock) | Keeps working |
| 0.1–1 s | Jetson | SLAM, Nav2, behaviour trees | Pi slows, then stops |
| 1–10 s | DGX | Task planning (`smart`); scene understanding once vision returns | Jetson finishes its goal, then waits |
| hours | dgx-2 | Isaac Lab sims, training from rosbags | — |

- **Transport:**
  - ROS 2 runs over Zenoh, with the router on the Jetson.
  - The Nav2 bridge maps `robot.<id>.cmd.goal` to Nav2 actions.
  - Rosbags stream to dgx-2 (30-day retention).
- **Vision:** not deployed (D19). The camera stays connected for teleoperation in Foxglove.
- **Physical-action policy:**
  - Every `robot.*` tool call needs a DefenseClaw allow decision plus scope.
  - Movement outside the docked area outside daytime hours needs your approval.

### 10.1 Simulation and robot learning

```
 robots/models/ (Git): robot description, one source → URDF → MJCF (MuJoCo) + USD (Isaac)
        │                 sensors: Oradar MS200 LiDAR, IMX219 camera, wheel encoders, IMU
        ▼
 ┌──────────────────────────── dgx-2 (overflow: dgx-1 overnight) ─────────────────────────────┐
 │ Isaac Lab 3.0 (Newton, headless)  ── thousands of parallel envs, RL (RSL-RL / skrl)        │
 │ Isaac Sim (RTX)                   ── realistic camera / LiDAR, synthetic data              │
 │ MuJoCo (Playground on MJX, or MuJoCo Warp) ── fast control policies, cross-check           │
 │ domain randomization (mass, friction, latency, sensor noise) · curriculum                  │
 └─────────────┬──────────────────────────────────────────────────────────────────────────────┘
               │ metrics, videos, checkpoints
               ▼
 MLflow (dgx-2): experiments · runs · policy registry (versions + stages)  ── SeaweedFS artifacts
               │
               ▼ evaluation gates (sec. 15.5)
 export: ONNX → TensorRT (Jetson)  |  ONNX Runtime (Pi, small policies)
               │  PR: robots/policies/<name>.yaml (MLflow version + checksum)
               ▼
 Jetson / Pi: policy node in ROS 2 ── always below the Pi's safety governor
               │
               ▼  rosbags of real runs → SeaweedFS → datasets → calibrate the simulation, imitation learning
```

| Part | Choice | Notes |
|---|---|---|
| Robot description | One source in `robots/models/`, converted to URDF, MJCF and USD | Measured dimensions, masses and wheel geometry of the Pi robot; sensor models |
| Isaac Lab | 3.0, headless Newton physics; installed with `uv` (aarch64 path) | Official DGX Spark support; driver ≥ 580.159 (Sparks have 580.178) |
| Isaac Sim | A version Isaac Lab 3.0 supports (newer than 5.1) | Only for RTX camera/LiDAR rendering and synthetic data. No livestream on Spark. |
| MuJoCo | MuJoCo + MuJoCo Playground (MJX/JAX) or MuJoCo Warp | Fast training and a second-simulator check of every policy |
| RL libraries | RSL-RL / skrl (Isaac Lab), Brax PPO (Playground) | — |
| Tracking | MLflow (Postgres + SeaweedFS) | Experiments, metrics, eval videos, policy registry |
| Scheduling | Sim jobs submitted to the GPU queue with a memory footprint; DGXMM's budget includes them | Batch priority, below interactive and robot models; one large sim job per Spark |
| Orchestration | Temporal workflow: train → evaluate (both simulators) → export → register → open PR | Long runs survive restarts |
| Agents | A "robot-learning" worker agent can propose experiments and submit jobs via the `jobs.submit` MCP tool (with approval) and read MLflow results | Reward or environment code written by agents runs only in a sandboxed job container |
| Viewing | Eval-episode videos in MLflow; Foxglove for rosbags; Newton/MuJoCo viewers locally when needed | — |

## 11. Data and backup

| Store | Where | Backup |
|---|---|---|
| Git (`nikghodki/homelab`) | GitHub + mirror on dgx-2 | Inherent |
| age key | Offline + password manager | Manual copy |
| etcd | servers | Snapshot every 6 h → SeaweedFS (7 days) |
| Postgres (LiteLLM, agent memory, Temporal, audit) | CNPG, primary dgx-2, standby dgx-1 | Continuous WAL archiving → SeaweedFS (30 days) |
| Home Assistant config, Hermes state, picoclaw, OpenBot workspaces | their hosts | restic daily → dgx-2 (30 days) |
| DefenseClaw audit | each host → Loki | restic daily (90 days) |
| Phoenix | dgx-2 | restic daily (30 days) |
| Metrics / logs / traces | dgx-2 | Not backed up; metrics kept 1 year, logs and traces 30 days |
| Model files | Spark NVMe + SeaweedFS | Not backed up (pinned revisions in Git; can be downloaded again) |
| Rosbags | dgx-2 | Not backed up; 30 days |
| Robot descriptions, task configs, policy manifests | Git (`robots/`) | Inherent |
| MLflow (experiments, registry metadata) | Postgres (CNPG) + SeaweedFS | CNPG backups; promoted policy artifacts in restic (forever) |
| Checkpoints, sim datasets, synthetic data | SeaweedFS on dgx-2 | Not backed up (reproducible from Git + seeds); 90 days |
| Off-site | USB drive or B2 | restic weekly copy (8 weeks) |

## 12. Security architecture

### 12.1 Layers

| # | Layer | Controls |
|---|---|---|
| 1 | Network | Tailscale ACL tags; LAN exposure rules (§4.3); CrowdSec on the HTTPS proxy; HTTPS everywhere |
| 2 | Identity | One identity per agent and device; 90-day key rotation; single-use Tailscale auth keys |
| 3 | Supply chain (CI) | gitleaks, TruffleHog, OSV-Scanner, Syft + Grype, Semgrep CE, CodeGuard, Trivy, kubeconform, Kyverno CLI, ansible-lint, skill-scanner, mcp-scanner (static), a2a-scanner, Agentic Radar, ModelScan; cosign keyless signing |
| 4 | Admission (home) | Kyverno: signed images only, no privileged pods (except an allowlist: Zenoh, ROS drivers), no `latest`, limits required |
| 5 | Agent runtime | DefenseClaw 1.0.9 hooks (strict or managed tier) in every framework; DefenseClaw guardrail plugin in LiteLLM (model and MCP calls); guard models; LiteLLM tool permissions and approvals |
| 6 | Host runtime | Tetragon with DefenseClaw kernel controls; DefenseClaw sensor, hook guardian, foreign-hook guard; kube-bench + Lynis monthly |
| 7 | Testing | Self-hosted runner on dgx-2: promptfoo on change, garak weekly, PyRIT monthly |
| 8 | Recovery | restic + Git rebuild; quarantine tag; secret rotation runbook |
| 9 | Visibility | DefenseClaw dashboards in Grafana; alerts on fail-open and gateway down |

### 12.2 DefenseClaw: every capability, on every agent

Version 1.0.9 or newer everywhere (dgx-1 is on 1.0.2, the Jetson on a dev build, the Pi on a custom Edge build).
Linux x86_64 and arm64 are supported.

#### Where each agent is covered

| Agent / path | Host | DefenseClaw route | Tier |
|---|---|---|---|
| Hermes (2 profiles) | Jetson | Hermes hook connector; gateway as a restarting system service | managed / strict (tool calls fail closed) |
| Claude Code, Codex, OpenCode | dgx-1, Omarchy | Hook connectors (one gateway, several connectors) | managed |
| Unattended coding agents | dgx-1, Omarchy | OpenShell sandbox (`defenseclaw sandbox`) | managed |
| picoclaw | Pi | **Edge Connector** (C engine: local rules, content inspection, rate limits including 10 physical actions per minute, audit log where each entry is chained to the last, so tampering shows); escalates undecided calls to the **Fleet gateway on dgx-1 over MQTT** (through the dedicated Fleet Mosquitto broker, D24); signed policy updates over MQTT | strict, works offline |
| LiteLLM (every model, MCP and A2A call) | dgx-1, dgx-2 | **Agent-gateway route**: our LiteLLM guardrail plugin calls DefenseClaw for each step | closed for tool calls |
| OpenBot (CopilotKit) | Omarchy | **Agent-gateway route** from OpenBot's policy gateway, plus LiteLLM for its model and tools | strict |
| OpenClaw | MacBook Air | OpenClaw connector | out of scope for now (D18) |

#### Capabilities and how we use them

| Capability | What it does | How we use it |
|---|---|---|
| Guardrails (rule packs) | Allow / alert / confirm / block on prompts, tool calls and responses | `strict` pack for agents that act; `balanced` for chat-only; per-connector settings in one gateway per host |
| CEL and OPA policies, protected files | Custom rules; protects credentials, sudoers, shell startup files and agent hook configs | Policies in `policies/defenseclaw/`, validated in CI with the rulepack check, shipped as bundles |
| User and group policies | Different policy per user or group | One profile for you, a stricter one for agent service users |
| LLM judge | Second opinion on unclear calls | `DEFENSECLAW_LLM_KEY` and base URL pointed at LiteLLM, so the judge runs on our own models |
| HITL (human in the loop) | Turns "confirm" findings into approval prompts | Native prompts where the connector can pause; otherwise **webhook → Hermes (WhatsApp) / ntfy**; shown on the HITL dashboard |
| Webhooks | Slack, PagerDuty, Webex, generic HMAC-signed | Generic HMAC webhook to the alert router (Hermes + ntfy) for high-severity events |
| Admission scanning | Scans skills, MCP servers and plugins when they appear; allow / warn / block by severity; `asset_policy` allow and block lists | `asset_policy` in Git; MCP servers must pass before LiteLLM registers them |
| skill-scanner, mcp-scanner, plugin scanner, code scan (CodeGuard / ClawShield) | Static and LLM-assisted scanning | In CI (GitHub Actions) and at home (continuous, on appearance) |
| Registries | Subscribe to skill / MCP catalogs; entries are fetched, scanned and auto-promoted | Subscribe to the catalogs we use; only clean entries become installable |
| **AI discovery** | Continuous fingerprinting of agents, local models, model servers, MCP servers, skills and providers, plus runtime detection of what actually ran | On every host; new or unknown AI ("shadow AI") raises an alert |
| **AIBOM** | `defenseclaw aibom scan --json`: live inventory of skills, plugins, MCP servers, agents, tools, models and memory per connector | Nightly job on every host; JSON kept on dgx-2 and diffed against the previous night; changes reported in the morning digest |
| Kernel controls (Tetragon, "Plane C") | Kernel-level observe / approve / enforce for AI agent processes; events joined to the agent and hook | Tetragon on the Sparks, the Jetson and Omarchy (replaces Tetragon); rollout in observe mode first, then enforce |
| Hook guardian, foreign-hook guard, sensor helper | Stops other hooks from changing a tool call after inspection; keeps hooks installed | Part of every managed install |
| Segmentation | Shows which layer sees and enforces protected paths, credentials, persistence, egress, blocked tools, process lineage and shadow AI | Used as the checklist when a host is onboarded |
| OpenShell sandboxes | Coding agents in skip-permissions mode, with every tool call and site judged; sandbox telemetry | Unattended coding agents; the Sandboxes dashboard |
| ACP guard | Sits between an ACP editor and a coding agent | Available; not used yet (no ACP editors in the fleet) |
| Semantic routing (vLLM Semantic Router sidecar) | Routes proxy traffic between model backends | Not used: LiteLLM does routing |
| Observability | OTLP logs, metrics and traces; redaction; end-user identity; Agent360 | OTLP to our collectors (section 13); redaction on; identity attribution on |
| TUI, command generator | Operator console; builds exact setup commands | Operator tools; generated commands are stored in `hosts/` |
| Splunk / Galileo destinations | Extra export targets | Not used (D10) |

#### Dashboards and alerts
- All **19 DefenseClaw Grafana dashboards** are copied into our Grafana from the DefenseClaw release (provisioned from
  `cluster/observe/grafana/dashboards/defenseclaw/`, with data sources mapped to VictoriaMetrics, Loki and Tempo):
  1. Overview
  2. Agent Activity (Live)
  3. Agent identity
  4. Identity & Users
  5. Agent360
  6. Blocked Events & Analysis
  7. AI Agent Usage & Detection
  8. AI Discovery Runtime Planes
  9. Hook Connectors
  10. Connector Detail
  11. Guardrail Evaluations
  12. Policy decisions
  13. HITL
  14. Findings
  15. Scanners (Ops)
  16. Proxy & LLM Guard
  17. Sandboxes
  18. Runtime & Reliability
  19. Fleet
- Its **Prometheus alert rules** (for example kernel denials, stale kernel acks) are loaded into vmalert.
- On each DefenseClaw upgrade, a CI job pulls the dashboards and rules from the release tag and opens a PR.

### 12.3 One request through the layers ("robot, check the kitchen")
1. Hermes receives a WhatsApp message from you (sender allowlist), and its DefenseClaw `pre_llm_call` hook runs.
2. LiteLLM checks Hermes's key, budget and allowed alias, then the DefenseClaw guardrail plugin and guard model run.
3. `smart` plans the request: navigate to the kitchen, report.
4. Hermes calls `robot.navigate` through LiteLLM's MCP gateway with its own key: tool permission, DefenseClaw
   verdict (`pre_mcp_call`), approval on WhatsApp, record.
5. The goal goes on NATS (`robot.pi.cmd.goal`), where Hermes's account is allowed to publish. The Nav2 bridge turns
   it into a Nav2 goal; the Jetson plans the path; the Pi drives under its safety governor.
6. The result comes back through `post_tool_call`, and output scanning redacts PII.
7. Every step shares one trace ID in Phoenix and Tempo.

## 13. Observability architecture

```
 every host: OTel Collector (contrib) ── scrapes fleet-metrics :9109, node, dcgm-exporter (Sparks),
     │                                   jetson-stats (Jetson); tails journald; receives OTLP
     │                                   (DefenseClaw gateways, agents, LiteLLM, Nav2 bridge)
     ▼
 dgx-2: VictoriaMetrics (Prometheus API) · Loki · Tempo · Phoenix (LLM/agent traces)
     ▼
 Grafana: Fleet · Models · Capacity · Robot · Security + 18 DefenseClaw dashboards (Overview, Hook
          Connectors, Agent360 …)
 vmalert + Gatus ──▶ alert router ──▶ Hermes (WhatsApp)  +  ntfy (backup)
```

| Signal | Source of truth |
|---|---|
| GB10 unified memory | fleet-metrics (DCGM reports GPU memory as N/A on GB10) |
| GPU utilization, power, clocks (Sparks) | dcgm-exporter |
| Jetson GPU / temperature | jetson-stats exporter |
| LLM tokens, latency, cost per agent | LiteLLM → Phoenix |
| Security verdicts | DefenseClaw OTLP → Loki and Tempo |

Splunk isn't deployed (D10). DefenseClaw's `--enterprise` HEC destination can be added later if a Splunk server
is available.

## 13a. Single pane of glass

```
                      you (browser / phone)  ── passkey ──▶  Pocket ID (OIDC)
                                │
                                ▼
            Caddy  ──(OIDC apps sign in directly; others via oauth2-proxy)──┐
                                │                                            │
                                ▼                                            ▼
   ┌──────────────── Fleet Console  ops.nghodki.ai  (standalone app) ──────────────┐   Grafana · Phoenix ·
   │ Overview · Alerts · Approvals · Agents · Models · Tools (MCP) · Security ·     │   Argo CD · DGXMM ·
   │ Robot · Deploys · Ask the fleet · Docs            (UI/UX design: later)       │   Home Assistant ·
   │ reads: Gatus, VictoriaMetrics, Alertmanager, DefenseClaw gateways + AIBOM,    │   Open WebUI
   │        LiteLLM (keys, spend, MCP, A2A), DGXMM, Argo CD, Kubernetes, GitHub,   │   (deep views, same
   │        NATS (robot), Home Assistant                                           │    sign-in, linked
   │ acts:  approve/deny · freeze agent · quarantine host · e-stop · load/unload   │    from the console)
   │        model · roll back  → each checked by DefenseClaw and written to audit  │
   │ embeds: Grafana panels (Fleet Home), Phoenix views                            │
   └──────────────────────────────────────────────────────────────────────────────┘
        ▲ alerts                     ▲ approvals
   Alertmanager ◀── vmalert, Gatus, DefenseClaw webhooks, Kubernetes events
        └─▶ Hermes (WhatsApp) · ntfy · Fleet Console   (acknowledge once, everywhere)
```

| Part | Choice | Notes |
|---|---|---|
| Sign-in | **Pocket ID** (passkeys, OIDC) | oauth2-proxy (or tinyauth) behind Caddy for apps without OIDC; every UI behind it |
| Front door | **Fleet Console**, standalone app at `ops.nghodki.ai` | Stack to be chosen with the UI design (FastAPI + React, like DGXMM, is the default assumption). Its own actions use a dedicated identity and go through DefenseClaw like an agent's. |
| Until the console exists | **Homepage** launcher at `ops.nghodki.ai` with live status widgets | Replaced by the console later |
| Data pane | Grafana **Fleet Home** dashboard + folders (Fleet, Models, Security with the 19 DefenseClaw boards, Agents, Robot, Capacity) | Data links: DefenseClaw log → Loki → Tempo trace → Phoenix |
| Alerts | **One Alertmanager**: vmalert, Gatus, DefenseClaw webhooks, Kubernetes events | Deduplication and grouping; routes to Hermes, ntfy and the console |
| Chat | "Ask the fleet": an ops agent through LiteLLM's MCP gateway with read-only tools (Grafana MCP, Argo CD, Kubernetes, DGXMM, DefenseClaw) | Anything that writes becomes an approval |
| Phone | Hermes on WhatsApp (status, approvals, e-stop) + ntfy; the console works on a phone screen | — |
| UI/UX | **To be designed later** | A throwaway demo (mock data) is in `~/homelab/console-demo/` |

## 14. CI/CD

```
 PR on github.com/nikghodki/homelab (private)
   ├─▶ GitHub-hosted runners: lint, schema and Kyverno CLI checks; secret, dependency, code and image scans;
   │     skill, MCP and agent-card scanners; ModelScan;  on merge: build → cosign keyless → push
   ├─▶ self-hosted ARC runner on dgx-2 (private repo only; may reach LiteLLM only):
   │     promptfoo (on agent/prompt change) · garak (weekly) · PyRIT (monthly)
   │     robot policies: MuJoCo smoke eval on every policy PR (minutes) · nightly Isaac Lab eval suite
   ▼ merge
 Argo CD (home) pulls cluster/  →  Kyverno admits signed images  →  deployed
 Ansible (from home: work Mac or ARC runner) applies hosts/ and robots/
 Renovate (GitHub App): weekly version-bump PRs
```

### 14.1 Workflow files
- `pr-checks.yml`
- `nightly-scan.yml`
- `build-sign.yml`
- `redteam.yml` (self-hosted)
- `renovate.json`

### 14.2 Rules
- Actions are pinned to commit SHAs.
- `permissions: read-all` by default.
- No age key in GitHub.
- Commits use the nikghodki noreply identity.

## 15. Key flows

### 15.1 Changing something
1. A PR goes up and CI runs on it.
2. You review and merge.
3. Argo CD syncs the cluster, or Ansible runs for host changes (check mode first).
4. Gatus and the dashboards confirm the change.
5. If it's bad: `git revert`.

### 15.2 Onboarding a model
1. Add `models/<name>.yaml` (source, revision, alias, mode).
2. DGXMM downloads it.
3. ModelScan checks it.
4. DGXMM calibrates its memory footprint and benchmarks it.
5. garak and promptfoo run against it on the self-hosted runner.
6. It shadows real traffic for 24 h.
7. The alias switches to it.
8. The old model is retired after 14 days.

### 15.3 Onboarding an agent
1. Add `agents/<name>/` (card, scopes, budget, connector, image).
2. CI runs a2a-scanner, Agentic Radar and promptfoo.
3. Argo CD deploys it, and its key and NATS user are created.
4. It runs in dry-run staging: tool calls are logged, not executed.
5. It goes live.

### 15.4 An alert
1. A signal crosses its threshold.
2. vmalert or Gatus fires.
3. Critical alerts go to both WhatsApp and ntfy, and repeat every 30 min until acknowledged.
4. The operator opens the runbook in `runbooks/`.

### 15.5 Training and shipping a robot policy
1. **Define** the task (for example "reach a named spot avoiding obstacles") in `robots/tasks/`, with the reward,
   termination rules and domain-randomization ranges.
2. **Train** on dgx-2: an Isaac Lab or MuJoCo job through the GPU queue, tracked in MLflow.
3. **Evaluate in both simulators** over a fixed set of seeds and scenes, measuring success rate, collisions, path
   length and smoothness. Both must pass their thresholds.
4. **Export** to ONNX, then TensorRT for the Jetson or ONNX Runtime for the Pi. Check that the exported model
   gives the same outputs as the original, within tolerance.
5. **Register** the version in MLflow and open a PR with `robots/policies/<name>.yaml` (version, checksum, limits).
   CI runs the MuJoCo smoke eval.
6. **Shadow on the robot:** the policy runs and its commands are logged, not executed.
7. **On blocks:** it drives with the wheels off the ground, and the safety-governor tests are run again.
8. **Speed-capped canary:** 25% speed, a fenced area, you watching.
9. **Live.** The previous version stays installed; rollback is one PR.
10. **Learn from real runs:** rosbags feed simulation calibration and the next training round.

## 16. Failure behaviour

| Event | Keeps working | Degrades |
|---|---|---|
| dgx-1 reboots | Cluster (dgx-2 + Jetson etcd), DNS and proxy (moved by kube-vip), NATS, Postgres (dgx-2 primary), Hermes, robot | `smart`/`vision` → dgx-2 or `fast` |
| dgx-2 reboots | Cluster (dgx-1 + Jetson), interactive models, Hermes | Observability, Phoenix, Argo CD, Temporal and batch pause; Postgres fails over to dgx-1 |
| Jetson down | Cluster (2 Sparks of 3 etcd), models | Hermes, HA and navigation; Pi falls back to reflexes |
| Jetson down **and** a Spark down | Running services | The cluster stops accepting changes (no quorum) until one returns |
| Omarchy down | Everything shared | OpenBot and workers pause; Temporal resumes them |
| Pi Wi-Fi drop | Safety governor, reflexes | Stops after 2 s |
| A DefenseClaw gateway down | — | That host's physical and write actions are refused; critical alert |
| GitHub down | Everything running | No new deploys |
| Internet down | Everything local | No downloads; no WhatsApp (ntfy works only if self-hosted) |

## 17. Operations summary

Full runbooks live in `runbooks/`.

### 17.1 Routine
- **Daily (automatic):** 08:00 digest on WhatsApp; backups; rescans; drift check.
- **Weekly:** garak and promptfoo (automatic). You read the report, merge Renovate PRs and review DefenseClaw
  blocks and approvals (~15 min).
- **Monthly (one evening):**
  - Upgrade window, in this order: back up and snapshot → Omarchy → Jetson → dgx-2 → dgx-1 → Pi (docked).
  - One restore test.
  - Access review.
  - PyRIT.
  - Safety-governor test.
- **Quarterly:** rotate secrets, capacity review, check the off-site backup, power drill.

### 17.2 Runbooks
- DefenseClaw down
- model alias down
- Spark reboot
- quorum loss
- disk full
- agent misbehaving (freeze)
- robot misbehaving (e-stop)
- security alert (quarantine)
- Wi-Fi outage
- power cut
- bad deploy (revert)

### 17.3 Power
- A UPS for both Sparks, the switch and the router.
- NUT shuts down in order: robot docks → Omarchy → Jetson workloads → dgx-2 → dgx-1 → Pi.
- Startup: router → dgx-1 → dgx-2 → Jetson → Omarchy → Pi.
