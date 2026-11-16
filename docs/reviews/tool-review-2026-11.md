# Tool review, November 2026

| | |
|---|---|
| Date | 2026-11-15 |
| Scope | Every tool in `docs/design.md` (D1–D25), `docs/architecture.md`, `decisions/`, `hosts/stacks/*`, `hosts/roles/*`, `cluster/`, `.github/workflows/*`, plus what actually runs on the hosts |
| Method | Repo read at `origin/main` 4a9383d. Memory measured read-only on 2026-11-15 ~18:20 PT: `docker stats --no-stream`, `k3s crictl stats` (working set; there is no metrics-server, so `kubectl top` doesn't work), `ps` RSS. Upstream data from the GitHub API (stars, license, latest release) and the vendors' docs, fetched the same day |
| Constraints | Free (OSS, or a free tier without lock-in), self-hosted, arm64 (2 × GB10, Jetson Orin, Pi 4) plus one 8 GB amd64 laptop; 5 hosts, 1 user plus family; low memory and low operational overhead beat scale |
| Status | Review only. Nothing was changed on any host. Recommendations that need your decision are marked **[decision]** |

**Bottom line.** The stack is mostly the right one for a small arm64 fleet, and almost everything is genuinely free.
The waste is in **duplicates and idle services**, not in bad choices: Coolify hosts zero apps, Temporal runs zero
workflows, nginx-gateway is a legacy hop behind Caddy, four Postgres instances and two Redis exist where one
of each would do, three secret scanners overlap, and the stock `otelcol-contrib` binary is the largest process on
the Pi. Three licensing flags need action or awareness: **Redis 7.4 (RSALv2/SSPL, not open source)**, **Phoenix
(Elastic License 2.0)** and **LiteLLM enterprise gating** of some features the design assumes.

**Single biggest simplification:** finish the P3.3 edge cutover and retire the hand-run `~/edge-gateway` on dgx-1
together with `nginx-gateway` and `edge-dnsmasq` (§2.1, §2.15). It removes the one part of the front door that
isn't in Git, two proxy hops, one DNS server, the Caddy-to-nginx double config for `model.`, `ha.` and
`voice-agent.`, and the dgx-1 single point of failure (F6), at the cost of work that is already planned.

---

## 1. Inventory

Memory: **m** = measured (working set or RSS, 2026-11-15), **e** = estimate. "—" = runs only in CI (GitHub-hosted
runners, no home memory). Versions are what is deployed or pinned; "latest" is noted where we are behind.

### 1.1 Config, IaC, GitOps

| Tool | Version in use | What it does here | Memory | License |
|---|---|---|---|---|
| Ansible (`ansible-core`) | 2.21.6 (CI); run from the work Mac / dgx-1 | Applies `hosts/` (roles, Compose stacks, timers) | — (runs on demand) | GPL-3.0 |
| SOPS + age | SOPS 3.x (latest 3.13.3), age 1.x | Encrypted `secrets/` and `cluster/**/*.enc.yaml` | — | MPL-2.0 / BSD-3 |
| Docker Compose | Docker Engine on every host | Interim stacks (`hosts/stacks/*`) until P3.7 | dockerd 120–135 MiB + containerd 75–165 MiB per host (m) | Apache-2.0 |
| k3s | v1.37.2+k3s1 (latest) | Cluster: dgx-1, dgx-2 servers; Jetson etcd + tainted worker; Omarchy agent | k3s-server 1.35 GiB on dgx-1 (m), 197 MiB on Jetson (m); k3s-agent 185 MiB on Omarchy (m) | Apache-2.0 |
| Argo CD | 3.6.1, chart 10.18.0 (latest) | Pull-based GitOps of `cluster/` (app of apps) | 497 MiB (controller 318, repo-server 117, server 39, redis 23) (m) | Apache-2.0 |
| KSOPS | 4.5.1 | SOPS decryption inside the Argo CD repo-server | 0 (init container) | Apache-2.0 |
| Helm | 3.x (Argo CD renders charts) | Argo CD, Kyverno, CNPG charts | — | Apache-2.0 |
| Renovate | Mend-hosted GitHub app (latest 44.240.0) | Weekly digest-pinned bump PRs | — | AGPL-3.0 |
| kube-vip | v1.3.1 (latest) | ARP VIPs .10 (API) and .11 (edge) | 28 MiB (2 pods) (m) | Apache-2.0 |
| kube-state-metrics | v2.20.0 | Cluster object metrics for VictoriaMetrics | 15 MiB (m) | Apache-2.0 |

### 1.2 Policy and admission

| Tool | Version | What it does here | Memory | License |
|---|---|---|---|---|
| Kyverno | 1.20.0, chart 3.10.0 (latest) | Signed images (`verify-images`), no privileged, limits, no `latest` | 213 MiB (admission ×2 sides + reports) (m) | Apache-2.0 |
| Kyverno CLI | 1.20.0 | Policy tests in CI | — | Apache-2.0 |

### 1.3 Network and edge

| Tool | Version | What it does here | Memory | License |
|---|---|---|---|---|
| Tailscale | 1.104.7 (latest) | Underlay, tags/ACLs, MagicDNS, split DNS, Serve | tailscaled 38–58 MiB per host (m) | BSD-3 (client); SaaS control plane, free Personal plan |
| Caddy, front door (`edge-caddy`, Docker, `~/edge-gateway`) | `caddy:2.11` (unpinned tag, not in repo) | TLS for `*.nghodki.ai`, routes to every UI | 22 MiB (m) | Apache-2.0 |
| Caddy, front door in k3s (`edge/caddy`, 2 replicas) | 2.11.9 (latest), by digest | P3.3 replacement, parallel test, no cutover yet | 36 MiB (2 pods) (m) | Apache-2.0 |
| Caddy, Fleet API proxy (`fleet` stack) | 2.11.9-alpine | TLS `:8971` → loopback DefenseClaw Fleet gateway, only `/api/v1/fleet/*` | 17 MiB (m) | Apache-2.0 |
| Caddy, MLflow job API (`ml` stack, `ml-api`) | 2.11.9-alpine | Basic auth for sim jobs on `:5000` → MLflow | 15 MiB (limit 128m) (m) | Apache-2.0 |
| nginx-gateway (legacy) | `nginx:alpine` (unpinned), config in `~/voice-assistant/nginx` | Behind edge-caddy: `model.` (`/v1/` → LiteLLM, `/dgxmm/`, `/tts/` → Kokoro), `ha.`, `voice-agent.` | 3 MiB (m) | BSD-2 |
| dnsmasq (`edge-dnsmasq`) | local build | `*.nghodki.ai` → dgx-1 until the P3.3 cutover | 1 MiB (m) | GPL-2.0/3.0 |
| CoreDNS (`edge` + k3s `kube-system`) | 1.14.7 (latest 1.15.0) | Edge zone (P3.3), cluster DNS, forward to edge-dnsmasq | 48 MiB (4 pods) (m) | Apache-2.0 |
| UFW | distro | Host firewall on one host | ~0 | GPL-3.0 |
| CrowdSec | planned (architecture §12) | Not deployed | — | MIT |

### 1.4 Identity

| Tool | Version | What it does here | Memory | License |
|---|---|---|---|---|
| Pocket ID | 2.19.2 (latest 2.19.3) | Passkey OIDC for Grafana, Argo CD, Phoenix, Temporal UI, oauth2-proxies | 44 MiB (m) | BSD-2 |
| oauth2-proxy ×3 | 7.15.6 (latest) | `alerting-status-proxy` (Gatus), `ops-oauth2-proxy` (Homepage), `ml-oauth2-proxy` (MLflow UI) | 11 + 13 + 8 = 32 MiB (m) | MIT |

### 1.5 Messaging

| Tool | Version | What it does here | Memory | License |
|---|---|---|---|---|
| NATS (JetStream + MQTT 3.1.1) | 2.15.3 (latest) | Fleet event bus; MQTT for picoclaw and HA | 12 MiB (m) | Apache-2.0 |
| Mosquitto | 2.1.2 (latest tag) | MQTT 5 broker for DefenseClaw Fleet only (D24) | 4 MiB (m) | EPL-2.0 / EDL-1.0 |

### 1.6 Observability

| Tool | Version | What it does here | Memory | License |
|---|---|---|---|---|
| OTel Collector (contrib), per host | 0.165.0 (latest) | hostmetrics, journald, scrape fleet-metrics/dcgm, OTLP in | dgx-1 95, Jetson 106, Omarchy 249, **Pi 222** MiB RSS (m) | Apache-2.0 |
| OTel Collector, 2 gateways (dgx-2) | 0.165.0 | `otel-fleet` and `otel-defenseclaw` | 124 + 68 MiB (m) | Apache-2.0 |
| VictoriaMetrics (single) | v1.156.0 (latest) | Metrics, 12-month retention | 243 MiB (m) | Apache-2.0 (some features enterprise-only) |
| vmalert | v1.156.0 | Alert rules incl. DefenseClaw's | 24 MiB (m) | Apache-2.0 |
| Alertmanager | 0.35.0 (latest) | One router for every alert source | 26 MiB (m) | Apache-2.0 |
| Loki | 3.7.10 (latest) | Logs (journald, DefenseClaw audit), 30 days | 315 MiB (m) | AGPL-3.0 |
| Tempo | 2.10.10 (latest **3.1.1**) | Traces, 30 days; config from DefenseClaw 1.0.9 | 98 MiB (m) | AGPL-3.0 |
| Grafana | 13.3.1 (latest) | Dashboards incl. 19 DefenseClaw boards | 270 MiB (m) | AGPL-3.0 |
| Arize Phoenix | 21.1.0 (latest) | LLM/agent traces | 48 MiB (m; little data yet) | **Elastic License 2.0** |
| Gatus | 5.38.0 (latest), on the Dell | Uptime checks (≈26 endpoints), ntfy alerts | 22 MiB (m) | Apache-2.0 |
| ntfy | 2.38.0 (latest), on the Dell | Phone push, backup alert channel | 32 MiB (m) | Apache-2.0 / GPL-2.0 |
| dcgm-exporter | 4.4.2-4.7.1 (latest 4.9.0) | GPU util/power/clocks on both Sparks | 41 + 52 MiB (m) | Apache-2.0 |
| fleet-metrics (custom) | in repo, ~500 lines Python, no deps | CPU/mem/GB10 unified memory/thermal/power, services on `:9109` | 11 MiB (m) | repo |
| jetson-stats exporter | **not deployed** (architecture §13 lists it) | — | — | AGPL-3.0 (jetson_stats) |
| Lynis | 3.0.9 on Jetson (latest 3.1.7) | Monthly host audit (role `lynis`) | 0 (on demand) | GPL-3.0 |

### 1.7 Supply chain and CI security (all GitHub-hosted, no home memory)

| Tool | Version | What it does here | License |
|---|---|---|---|
| GitHub Actions | Free plan (decision 0001) | `pr-checks`, `nightly-scan`, `build-sign` | SaaS |
| gitleaks | 8.30.1 (Mar 2026; **maintenance-only**) | Secret scan, full history, PR + nightly | MIT |
| TruffleHog | 3.99.9 | Verified-secret scan on PRs | AGPL-3.0 |
| OSV-Scanner | 2.7.1 | Dependency vulns (source), PR + nightly | Apache-2.0 |
| Trivy | 0.76.2 | `fs` vulns + misconfig + **secrets** on PRs; nightly image scan; CycloneDX SBOM | Apache-2.0 |
| Semgrep CE | 1.185.0, `p/default` | Code scan | Engine LGPL-2.1; **rules: Semgrep Rules License** |
| cosign (keyless) | 3.1.4 | Sign images and SBOM attestations | Apache-2.0 |
| BuildKit SBOM (SPDX) | buildkit 0.35.0 | SBOM inside the image index (this is the "syft" role; syft itself is not used) | Apache-2.0 |
| actionlint | 1.7.12 | Workflow lint (the image bundles shellcheck for `run:` blocks) | MIT |
| yamllint | 1.38.0 | YAML lint | GPL-3.0 |
| ansible-lint | 26.11.0 | Ansible lint | MIT/GPL-3.0 |
| kubeconform | 0.8.0 | Manifest schema check | Apache-2.0 |
| pytest | 9.2.0 | Unit tests (fleet-metrics, guardrail, governor, AIBOM, scripts) | MIT |
| uv | used for Isaac Lab installs; CI uses `pip --require-hashes` | Python envs | Apache-2.0/MIT |
| **Not used** | shellcheck (standalone, for `.github/scripts/*.sh` and `hosts/`), hadolint, kube-linter, syft/grype | — | — |

### 1.8 AI security

| Tool | Version | What it does here | Memory | License |
|---|---|---|---|---|
| DefenseClaw (gateway, hooks, Fleet gateway) | 1.0.9 (latest) on dgx-1, Jetson | Hooks for Hermes and coding agents, Fleet gateway on dgx-1 | dgx-1 78 MiB; **Jetson 566 + 125 + 72 MiB** (two users' gateways + watchdogs) (m) | Apache-2.0 |
| DefenseClaw Edge Connector | Pi | picoclaw guard, escalates over MQTT 5 | small (e) | Apache-2.0 |
| DefenseClaw `aibom` | 1.0.9 | Nightly per-connector inventory | on demand | Apache-2.0 |
| Cisco AIBOM (`cisco-aibom`) | 1.10.1 (latest) | CI artifact + nightly fleet scan of code and images | on demand; **1.1 GiB RSS on the Jetson while running** (m), MemoryMax 4G (6G on Sparks) | Apache-2.0 |
| mcp-scanner | 4.8.7 | CI scan of `tools/*/tools.json` | — | Apache-2.0 |
| skill-scanner | 2.3.2 | CI + inside DefenseClaw | — | Apache-2.0 |
| a2a-scanner | 1.0.1 (last push Apr 2026) | CI scan of agent cards | — | Apache-2.0 |
| Agentic Radar | 0.14.2 | CI report on agent code | — | Apache-2.0 |

### 1.9 AI/ML platform

| Tool | Version | What it does here | Memory | License |
|---|---|---|---|---|
| LiteLLM proxy | 1.109.1 (latest), by digest | Model/MCP/A2A gateway | 1.03 GiB (4 workers) (m) | MIT core + `enterprise/` commercial |
| LiteLLM Postgres | 16.15 | LiteLLM DB (hand-run) | 35 MiB (m) | PostgreSQL |
| LiteLLM Redis | **7.4.12** (`redis:7-alpine`) | Cache / rate-limit state | 7 MiB (m) | **RSALv2 / SSPLv1** |
| DGXMM (custom) + vLLM / llama.cpp engines | in-house; engines per model | GPU owner, planner, engines | dgxmm 96 MiB; engine containers 4.9–7.5 GiB (m) | own / Apache-2.0 / MIT |
| Open WebUI | 0.13.3 (latest) | Chat UI | 53 MiB (m) | **Open WebUI License** (BSD-3 + branding clause) |
| MLflow (+ its Postgres) | 3.18.0; PG 17.12 | Experiments, policy registry | 55 + 19 MiB (m) | Apache-2.0 |
| Temporal (server, UI, admin-tools, Postgres) | 1.32.2 (latest), UI 2.58.1; PG 17.12 | Durable workflows, **0 workflows registered** (no `temporalio` code in the repo) | 132 + 11 + 1 + 36 = 180 MiB (m) | MIT |
| Isaac Lab | 3.0.0 (kitless image) | RL training on the Sparks | job-time (≤16 GiB limit) | BSD-3 (Isaac Sim/Kit parts: NVIDIA licenses) |
| MuJoCo / MJX / Playground / Brax / JAX | Playground 0.2.0, JAX 0.9.2 | Fast policy training, second simulator | job-time | Apache-2.0 |
| LiveKit server | 1.13.5 on Jetson (latest 1.13.11), `--dev` | Voice agent transport | 337 MiB (m) | Apache-2.0 |

### 1.10 Agents, robotics, apps

| Tool | Version | What it does here | Memory | License |
|---|---|---|---|---|
| Hermes (hermes-agent) | host install, 2 profiles | Front-door agent, WhatsApp | 219 + 218 MiB (m) | MIT |
| picoclaw | Pi | Robot skills agent | 30 MiB (m) | MIT |
| ROS 2 Kilted + rmw_zenoh + Zenoh router | `homelab/ros-zenoh:kilted-1` | Robot transport | router 91 MiB (m) | Apache-2.0 / EPL-2.0 |
| Home Assistant | 2026.11.1 via **`:stable` (unpinned, hand-run)** | Home control | 487 MiB (m) | Apache-2.0 |
| Coolify (+ Postgres 15, Redis 7.4, sentinel) | 4.7.3 (latest 4.7.5) | Self-hosted PaaS; **0 applications, 0 services, 0 databases** (its DB, read-only query) | 149 + 12 + 7 + 9 = 177 MiB (m) | Apache-2.0 |
| Homepage | 2.8.0 (latest), on the Dell | `ops.nghodki.ai` launcher | 113 MiB (m) | GPL-3.0 |
| restic + rest-server | restic 0.19.1; rest-server 0.14.0 | Backups, **off** (decision 0002); rest-server running anyway on dgx-2 | 4 MiB (m) | BSD-2 |
| CloudNativePG operator | 1.30.1 (latest) | Planned Postgres clusters | 26 MiB (m) | Apache-2.0 |
| SeaweedFS | planned | Object store for etcd snapshots, WAL, MLflow artifacts | — (est. 150–300 MiB) | Apache-2.0 |

### 1.11 Memory totals for non-model services (measured)

| Host | Non-model services, approx. | Notes |
|---|---|---|
| dgx-1 | ~3.8 GiB | k3s-server 1.35 GiB and LiteLLM 1.03 GiB are most of it; Coolify 177 MiB is pure overhead |
| dgx-2 | ~2 GiB plus k3s-server | observe stack ~1.2 GiB; Temporal 180 MiB idle |
| Jetson | ~3.0 GiB of 7.4 | DefenseClaw gateways ~0.76 GiB, Hermes 0.44, HA 0.49, LiveKit 0.34, k3s 0.2; only ~3.1 GiB available, and Cisco AIBOM can take 1.1+ GiB on top while it runs |
| Omarchy | ~0.85 GiB of 7.7 (+ desktop) | otelcol 249 MiB is the biggest fleet process; Homepage 113 MiB |
| Pi | ~0.65 GiB of 3.7 | otelcol 222 MiB is a third of it; the desktop (labwc, panel, pcmanfm ≈ 0.25 GiB) is still running until D17's Lite reinstall |

---

## 2. Overlap analysis

Each entry: the overlap, the recommendation, the tradeoff.

### 2.1 nginx-gateway vs Caddy
- **Overlap.** `edge-caddy` terminates TLS and then, for `model.`, `ha.`, `voice-agent.` and the catch-all `:80`,
  forwards to `nginx-gateway`, which does path routing (`/v1/` → LiteLLM, `/dgxmm/` → DGXMM, `/tts/` → Kokoro) that
  Caddy does natively (`handle_path`). Its config lives in `~/voice-assistant/nginx/`, outside the repo; F7 recorded
  117 restarts.
- **Recommendation: retire** (do now, as part of the P3.3 cutover). Port its ~10 locations into
  `cluster/platform/edge` Caddy routes, check with Gatus, then stop the container. Rollback: `rollback-nginx.txt`.
- **Tradeoff.** Memory saving is tiny (3 MiB). The win is one less hop, one less config language, and nothing in the
  front door outside Git.

### 2.2 Several Caddy and oauth2-proxy instances vs one
- **Caddy (5 today: edge-caddy, 2 edge pods, Fleet proxy, ml-api).**
  - After cutover, `edge-caddy` (Docker) goes, leaving the 2 k3s replicas.
  - The **Fleet API proxy must stay separate**: it reaches a loopback-only gateway, so it is host-network on dgx-1
    (architecture §3.1). Keep.
  - **ml-api** only adds basic auth on `:5000` for sim jobs. Fold it into the front door as an
    `mlflow-api.nghodki.ai` route with `basic_auth` (or a LiteLLM-style bearer), or drop it when sim jobs run as
    pods and reach MLflow over a ClusterIP with a NetworkPolicy. Consider later (P3.7).
- **oauth2-proxy (3 today).**
  - **Gatus has native OIDC** (`security.oidc` in its config) and can use Pocket ID directly, so
    `alerting-status-proxy` can go. That also keeps the alerting path on the Dell self-contained.
  - Homepage and the MLflow UI: one oauth2-proxy with `cookie_domain=.nghodki.ai` and `whitelist_domains`, called
    by the front-door Caddy with `forward_auth … uri /oauth2/auth`, protects any number of OIDC-less apps
    (Homepage, MLflow, DGXMM UI, later anything else). Run it as one Deployment in `console`.
  - A Caddy auth plugin (caddy-security) would remove oauth2-proxy completely but means a custom Caddy build and a
    less widely used auth stack; tinyauth (AGPL-3.0) is lighter but young. Not worth it.
- **Recommendation: consolidate** to 1 oauth2-proxy (forward_auth) + Gatus native OIDC; 3 Caddy after cutover
  (2 edge replicas + Fleet proxy), later 2-3.
- **Tradeoff.** Saves ~20 MiB and two containers; the real gain is that adding a protected app becomes a one-line
  Caddy change. Cost: the single proxy becomes a dependency of several UIs (run 2 replicas when the Sparks have
  room). The Dell's Homepage would then depend on the Sparks' front door, which it already does for TLS.

### 2.3 Mosquitto vs NATS (MQTT 5? EMQX? NanoMQ?)
- **Facts (2026-11).** NATS's MQTT listener implements **3.1.1 only**; "a device that requests MQTT v5 is rejected
  at connect" ([NATS MQTT docs](https://docs.nats.io/running-a-nats-service/configuration/mqtt)). nats-server 2.15.3
  (2026-11-11) didn't change that. The DefenseClaw Fleet gateway needs MQTT 5 (D24).
- **EMQX**: Business Source License 1.1 from 5.9.0, free in production only on a single node, each version becomes
  Apache-2.0 after four years ([LICENSE](https://github.com/emqx/emqx/blob/master/LICENSE)). Free for us today but
  not open source, and heavier (Erlang VM, ~300–500 MiB). Don't use it.
- **NanoMQ** (MIT, 0.25.7, 2026-10-21, 2.7k stars) supports MQTT 5 and is tiny, but it is a broker only; it can't
  replace JetStream.
- **Recommendation: keep both.** Mosquitto uses 4 MiB, is a clean MQTT 5 implementation, and isolating the security
  control channel from the general bus is a good property in its own right. Re-check when NATS ships MQTT 5.
- **Tradeoff.** Two brokers to patch; negligible memory.

### 2.4 Tempo vs Phoenix
- **Overlap.** Both store OTLP traces. Tempo stores every trace (DefenseClaw, services) for Grafana and the
  DefenseClaw dashboards; Phoenix is an LLM-specific UI (prompts, tokens, evals, sessions).
- **Recommendation: keep both.** Neither replaces the other: Phoenix doesn't serve Grafana's Tempo datasource or the
  DefenseClaw dashboards, and Tempo has no LLM span views or evals. Send LLM spans to both via the OTel gateway
  (already the design).
- **Notes.** Phoenix is **Elastic License 2.0**: free to self-host, not OSI open source (§4). Tempo 3.x (latest
  3.1.1) removed ingesters and v2 blocks; single-binary mode still exists and needs no Kafka
  ([v3.0.0 notes](https://github.com/grafana/tempo/releases/tag/v3.0.0)). Our config comes from DefenseClaw's bundle,
  so upgrade Tempo when DefenseClaw ships a 3.x config, not before (Renovate: hold the major).
- Langfuse (MIT core, now owned by ClickHouse) needs ClickHouse, Redis and S3; too heavy to swap in.

### 2.5 Gatus vs blackbox_exporter + vmalert
- **Overlap.** Both can probe HTTP/TCP and alert.
- **Recommendation: keep Gatus.** It runs on the Dell precisely so alerts survive a Spark or the observe stack being
  down (decision 0009). blackbox_exporter + vmalert would put probing back on dgx-2. Gatus costs 22 MiB and has a
  status page. Optional: let the OTel gateway scrape Gatus's `/metrics` so probe history is in VictoriaMetrics.
- **Tradeoff.** Two alert-rule languages (Gatus conditions, MetricsQL); acceptable.

### 2.6 Trivy vs OSV-Scanner vs gitleaks (and TruffleHog)
- **Overlap.** Three secret scanners on every PR (gitleaks, TruffleHog verified-only, Trivy `fs` secrets) and two
  dependency scanners (OSV, Trivy `fs` vuln).
- **Recommendation: narrow the scopes; don't add or drop tools wholesale.**
  - **Trivy**: images (nightly), misconfig (Dockerfiles, Kubernetes, Compose), SBOM. Run `fs` with
    `--scanners vuln,misconfig` (drop `secret`).
  - **OSV-Scanner**: source dependencies (better lockfile coverage; same OSV data). Keep.
  - **gitleaks**: history secret scan, but it is now **maintenance-only** ("security patches only"; the author has
    moved to [Betterleaks](https://github.com/betterleaks/betterleaks), MIT, v1.10.1, 2026-11-12)
    ([gitleaks README](https://github.com/gitleaks/gitleaks)). Consider switching to Betterleaks when it has a
    digest-pinnable image and a few more months of releases; until then gitleaks is fine.
  - **TruffleHog** (AGPL-3.0): keep; verified-secret detection is a different signal.
- **Trivy supply-chain incident.** In March 2026 attackers published a malicious Trivy v0.69.4, malicious Docker Hub
  tags 0.69.5/0.69.6, and force-pushed 76 of 77 `trivy-action` tags
  ([Aqua](https://www.aquasec.com/blog/trivy-supply-chain-attack-what-you-need-to-know/)). We use 0.76.2 by digest
  via `docker run`, not the action, which is the recommended posture. Keep digest pinning for every scanner.
- **Tradeoff.** CI minutes only; no home memory. Fewer duplicate findings to triage.
- **Gaps.** Add standalone **shellcheck** for `.github/scripts/*.sh` and shell in `hosts/` (cheap, high value).
  hadolint is optional (Trivy misconfig covers Dockerfiles); kube-linter is redundant with kubeconform + Kyverno CLI.

### 2.7 The two AIBOM tools
- **Overlap.** Both produce an AI bill of materials. DefenseClaw `aibom` = what each connector has *connected at
  runtime* (skills, plugins, MCP servers, models, memory). Cisco AIBOM = what the *code and images* contain.
  runbooks/aibom.md already explains this.
- **Recommendation: keep both, but change where Cisco AIBOM runs.** It took **1.1 GiB RSS on the Jetson** during
  the nightly run (MemoryMax 4G on a host with ~3 GiB available). Image scans don't need to run on the host that
  runs the image: scan the Jetson's and Pi's images by digest from dgx-2, and keep only the code scan (or nothing)
  on the Jetson and Pi. CI already scans the repo.
- **Tradeoff.** Loses the "what is literally on this disk" property for images pulled by hand; the hand-run images
  (HA, LiveKit) should be pinned in Git anyway (§2.17).

### 2.8 Coolify vs Argo CD/k3s
- **Overlap.** Both deploy apps. Coolify on dgx-1 hosts **0 applications, 0 services and 0 databases**, and holds
  the Docker socket (root-equivalent).
- **Recommendation: retire Coolify** **[decision]** (it was a "useful piece" you chose before the fleet). Saves
  177 MiB, a Postgres 15, a Redis 7.4 (RSAL/SSPL), a `coolify.nghodki.ai` route and an attack surface. If you want a
  "deploy an app from a repo" button later, an Argo CD Application per app (or Argo CD's UI "New App") covers it.
- **Tradeoff.** Losing a PaaS UI you don't use. Export `/data/coolify` before removing it.

### 2.9 fleet-metrics vs node_exporter + jetson-stats + dcgm
- **Overlap.** CPU/memory/disk overlap with the OTel `hostmetrics` receiver; GPU overlaps with dcgm-exporter.
- **Unique.** GB10 unified memory (DCGM reports N/A on GB10), thermal and power from hwmon, and the `/services`
  view for the console. 11 MiB, ~500 lines, no dependencies, tested in CI.
- **Recommendation: keep fleet-metrics; don't add node_exporter** (OTel hostmetrics already covers it, and the
  collector can read hwmon via its own scrapers or keep fleet-metrics for thermal). For the Jetson, either add
  tegrastats parsing to fleet-metrics or deploy a jetson-stats exporter (AGPL-3.0, needs the `jtop` service, ~40–60
  MiB e); the architecture claims one exists but none is deployed. Prefer extending fleet-metrics (no new daemon
  on a 7.4 GiB host).
- **Tradeoff.** Owning ~500 lines of code vs one more exporter.

### 2.10 Temporal vs lighter options
- **Facts.** Temporal 1.32.2 runs on dgx-2 (180 MiB incl. Postgres) with **no workflow code in the repo**. Planned
  uses: worker agents on Omarchy that survive reboots (P4.7) and the train → eval → export → register → PR
  pipeline (P6.6).
- **Options.**
  - Kubernetes Jobs/CronJobs: free, already there; no multi-step durable state.
  - **Argo Workflows** (Apache-2.0, 4.1.6, 2026-10-22, 17k stars): DAGs of pods, artifacts, retries, ~100–200 MiB
    (controller + server), same project family as Argo CD; natural for GPU/sim jobs that are pods anyway.
  - Hatchet (MIT, 0.114.x, Postgres-backed) and Prefect (Apache-2.0, 3.9.3, Python-native, server ~300–500 MiB):
    good developer experience, but another server and DB for few jobs.
  - Temporal: the best fit for long-running *agent* code (durable functions in Python), the heaviest operationally
    (4 containers, schema migrations).
- **Recommendation: consider later** **[decision]**. Don't move Temporal into k3s in P3.7; leave it stopped (or
  running, it's small) until P6.6 has its first real workflow. At P6.6 decide between Temporal (if agent workflows
  in code are the main use) and Argo Workflows (if the jobs are mostly containers). For this fleet's mostly-pod
  batch jobs, Argo Workflows is the likely simpler fit.
- **Tradeoff.** Temporal is already integrated with Pocket ID and Gatus; switching later costs those integrations.

### 2.11 Separate Postgres instances vs one CNPG cluster
- **Today: 4 instances** (LiteLLM PG16, Coolify PG15, MLflow PG17, Temporal PG17), ~100 MiB together, 3 major
  versions, 4 backup stories (none running).
- **Recommendation: consolidate** into one CNPG cluster in `data` (already P3.7): one database and role per app,
  primary dgx-2, standby dgx-1, WAL archive to SeaweedFS. Coolify's disappears with Coolify (§2.8). Use PG 17 (or 18)
  throughout; LiteLLM's PG16 dump/restore happens at the move anyway.
- **Tradeoff.** Memory roughly the same (one primary + standby ≈ 2 × ~60 MiB + shared buffers you choose); the win
  is one backup, one upgrade, one HA path. A noisy app can affect the others; set per-role `connection limit` and
  `statement_timeout`.

### 2.12 Homepage vs Grafana Fleet Home
- **Overlap.** Both are "start here" pages. Homepage (113 MiB on the 8 GB Dell) is the interim launcher until the
  Fleet Console (D23).
- **Recommendation: keep for now; retire when Fleet Home or the console exists** (consider later). A Grafana
  dashboard with a "links" panel plus Gatus's status page cover the launcher role. Saves 113 + 13 MiB on the Dell
  together with its oauth2-proxy.
- **Tradeoff.** Homepage's live widgets are nicer than a links panel; Grafana is already on the critical path.

### 2.13 Loki vs VictoriaLogs
- **Facts.** VictoriaLogs (Apache-2.0, v1.54.0, 2026-11-13) claims "up to 30x less RAM and up to 15x less disk" than
  Loki, accepts OTLP and Loki push, runs as a single binary
  ([docs](https://docs.victoriametrics.com/victorialogs/)). It uses LogsQL, not LogQL, and Grafana alerting can't
  show its datasource-managed rules.
- **Recommendation: keep Loki** (D9). The 19 DefenseClaw dashboards and its alert rules are written in LogQL, and
  every DefenseClaw upgrade re-syncs them (`defenseclaw-bundle.py`). Rewriting them for LogsQL would fork from
  upstream. Loki uses 315 MiB here; the saving (~200 MiB e) doesn't pay for the fork.
- **Revisit** if DefenseClaw ships VictoriaLogs dashboards, or if Loki grows past ~1 GiB.
  VictoriaTraces (v0.13, pre-1.0) is not a Tempo replacement yet.

### 2.14 restic vs Kopia/Borg
- **Facts.** restic 0.19.1 (BSD-2, 37k stars); Kopia 0.23.1 (Apache-2.0, has a UI and built-in S3/compression,
  ~14.7k stars); Borg 1.4.5 (BSD, needs SSH to a Borg server; Borg 2 still not final).
- **Recommendation: keep restic** (keep as is). It is configured and tested in the repo, has native S3 (so the
  planned SeaweedFS can replace rest-server), and arm64 builds. Kopia's advantages (UI, policies) don't justify
  re-doing roles. Turn backups on when you decide (decision 0002); meanwhile, `backup-rest-server-1` on dgx-2 runs
  but receives nothing: stop it or leave it (4 MiB).
- **Tradeoff.** None meaningful.

### 2.15 dnsmasq / CoreDNS
- **Overlap.** `edge-dnsmasq` (Docker, dgx-1) answers `*.nghodki.ai` today; CoreDNS in `edge` is the built
  replacement (decision 0007) and the cluster CoreDNS forwards to dnsmasq for pod lookups.
- **Recommendation: finish the cutover and retire dnsmasq** (do now). Point Tailscale split DNS and the router at the
  CoreDNS VIP, then remove the forward from the cluster zone.
- **Tradeoff.** CoreDNS on the Sparks makes DNS depend on a Spark being up, which is the HA design (kube-vip moves
  the VIP). For the family, consider keeping a secondary resolver on the router (not the fleet) so the internet
  keeps working if both Sparks are down.

### 2.16 Other overlaps found
- **Two OTel gateways on dgx-2** (`otel-fleet` 124 MiB, `otel-defenseclaw` 68 MiB). One collector with two pipelines
  would save ~60 MiB, but the DefenseClaw one tracks upstream config. Keep as is unless memory gets tight.
- **otelcol-contrib on small hosts** (222 MiB on the Pi, 249 on the Dell). The contrib distribution bundles hundreds
  of components. Build a fleet distribution with the
  [OpenTelemetry Collector Builder](https://opentelemetry.io/docs/collector/custom-collector/) containing only what
  `config.yaml.j2` uses (hostmetrics, journald, prometheus, otlp, resourcedetection, resource, batch,
  memory_limiter, otlp/otlphttp exporters), and set `GOMEMLIMIT` + `memory_limiter`. Expect ~100–150 MiB saved per
  small host (e). Grafana Alloy (Apache-2.0) is an alternative but no lighter in practice and changes the config
  language; stay on OTel.
- **Two Redis** (LiteLLM, Coolify) both on 7.4 (RSAL/SSPL): Coolify's goes with Coolify; replace LiteLLM's with
  **Valkey** (BSD-3, Linux Foundation, drop-in) (§4).
- **Two DefenseClaw gateways on the Jetson** (one per Hermes user) at ~0.76 GiB together. DefenseClaw supports
  several connectors per gateway (architecture §12.2 says "one gateway, several connectors" for coding agents). If
  the per-user split isn't required for isolation, one gateway per host would save ~0.3–0.4 GiB on the tightest
  host **[decision]** (it changes the per-user policy boundary).

### 2.17 Drift found during the review (not overlaps, but cheap to fix)
- Home Assistant runs `ghcr.io/home-assistant/home-assistant:stable` (unpinned; 2026.11.1 today) and LiveKit runs
  `--dev`, both hand-run on the Jetson; LiteLLM, Open WebUI and edge-gateway are hand-run on dgx-1 (architecture
  §3.3 already lists the last three). Pin by digest and bring into `hosts/stacks` so Renovate sees them.
- Behind latest: Pocket ID 2.19.2 → 2.19.3, dcgm-exporter 4.4.2 → 4.9.0, CoreDNS 1.14.7 → 1.15.0, Lynis 3.0.9 →
  3.1.7 (Jetson), LiveKit 1.13.5 → 1.13.11, Coolify 4.7.3 → 4.7.5 (moot if retired), Tempo 2.10 → 3.1 (hold, §2.4).
- `docs/architecture.md` §13 lists a jetson-stats exporter that isn't deployed.

---

## 3. Best-in-class check by category

Maturity numbers from the GitHub API on 2026-11-15 (stars; latest release and date). "Fit" = still the best choice
for a 5-host arm64 home fleet, counting migration cost.

| Category | Current | Top free options in 2026 (stars; latest release) | arm64 / resources | Fit |
|---|---|---|---|---|
| Orchestration | k3s | [k3s](https://github.com/k3s-io/k3s) (34k; v1.37.2, 2026-11-03); k0s; Talos; Nomad (BSL, no) | all arm64; k3s server ~0.2–1.4 GiB | **Keep** |
| GitOps | Argo CD + KSOPS | [Argo CD](https://github.com/argoproj/argo-cd) (25k; v3.6.1, 2026-11-04); [Flux](https://github.com/fluxcd/flux2) (8.5k; v2.10.0, 2026-10-26) | Argo ~500 MiB; Flux ~150–250 MiB (e), no UI | **Keep** (Flux is lighter, but the UI and OIDC are in the design; decision 0006) |
| Config mgmt / secrets | Ansible, SOPS+age | [Ansible](https://github.com/ansible/ansible) (71k); [SOPS](https://github.com/getsops/sops) (24k; v3.13.3, 2026-07-23); OpenBao for a vault | — | **Keep** |
| Dependency bumps | Renovate | [Renovate](https://github.com/renovatebot/renovate) (23k; 44.240.0, 2026-11-16); Dependabot | SaaS app (free) or self-run CLI | **Keep** |
| Admission | Kyverno | [Kyverno](https://github.com/kyverno/kyverno) (8.3k; v1.20.0, 2026-11-12); Gatekeeper; built-in ValidatingAdmissionPolicy + `sigstore/policy-controller` | Kyverno ~210 MiB | **Keep** (image verification + CEL policies in one) |
| VPN / underlay | Tailscale | [Tailscale](https://github.com/tailscale/tailscale) (39k; v1.104.7, 2026-11-12); [Headscale](https://github.com/juanfont/headscale) (46k; v0.29.7, 2026-10-30); NetBird; plain WireGuard | ~40–60 MiB per host | **Keep**; Headscale is the exit if the free plan changes (§4) |
| Reverse proxy | Caddy | [Caddy](https://github.com/caddyserver/caddy) (79k; v2.11.9, 2026-11-05); Traefik; nginx | 15–25 MiB | **Keep**; retire nginx (§2.1) |
| DNS | dnsmasq → CoreDNS | [CoreDNS](https://github.com/coredns/coredns) (14k; v1.15.0, 2026-10-21); AdGuard Home (38k; v0.107.80); Pi-hole | ~10–25 MiB | **Keep CoreDNS**; AdGuard Home only if you want family ad-blocking (separate concern) |
| VIP / LB | kube-vip | [kube-vip](https://github.com/kube-vip/kube-vip) (3k; v1.3.1, 2026-10-19); MetalLB; k3s ServiceLB | ~15 MiB/pod | **Keep** (one tool for API + service VIPs) |
| OIDC provider | Pocket ID | [Pocket ID](https://github.com/pocket-id/pocket-id) (10k; v2.19.3, 2026-11-15); [Authelia](https://github.com/authelia/authelia) (30k; v4.39.28); Authentik (26k; MIT + enterprise) | Pocket ID ~45 MiB; Authentik ~0.7–1 GiB | **Keep** (passkey-only, smallest) |
| Auth proxy | oauth2-proxy | [oauth2-proxy](https://github.com/oauth2-proxy/oauth2-proxy) (15k; v7.15.6, 2026-11-05); [tinyauth](https://github.com/tinyauthapp/tinyauth) (8.5k, AGPL; v5.2.0, 2026-09-07); Authelia | ~10–15 MiB | **Keep, one instance** (§2.2) |
| Event bus | NATS | [NATS](https://github.com/nats-io/nats-server) (21k; v2.15.3, 2026-11-11); Redpanda/Kafka (too heavy); Valkey streams | ~12 MiB | **Keep** |
| MQTT 5 broker | Mosquitto | Mosquitto (11k; 2.1.2); [NanoMQ](https://github.com/nanomq/nanomq) (2.7k, MIT; 0.25.7, 2026-10-21); EMQX (17k, **BSL**) | Mosquitto ~5 MiB | **Keep** |
| Collector | OTel contrib | [OTel Collector](https://github.com/open-telemetry/opentelemetry-collector-releases) (v0.165.0, 2026-11-07); [Grafana Alloy](https://github.com/grafana/alloy) (3.7k; v1.22.0); vmagent | contrib 95–250 MiB | **Keep OTel, build a slim distro** (§2.16) |
| Metrics | VictoriaMetrics | [VictoriaMetrics](https://github.com/VictoriaMetrics/VictoriaMetrics) (18k; v1.156.0, 2026-11-09); Prometheus; Mimir (heavy) | ~240 MiB | **Keep** |
| Logs | Loki | [Loki](https://github.com/grafana/loki) (29k; v3.7.10, 2026-11-13); [VictoriaLogs](https://github.com/VictoriaMetrics/VictoriaLogs) (2.5k; v1.54.0, 2026-11-13) | Loki ~315 MiB; VL less | **Keep** (DefenseClaw dashboards, §2.13) |
| Traces | Tempo | [Tempo](https://github.com/grafana/tempo) (5.6k; v3.1.1, 2026-10-21); Jaeger v2; [VictoriaTraces](https://github.com/VictoriaMetrics/VictoriaTraces) (0.5k; v0.13.0) | Tempo ~100 MiB | **Keep**; upgrade to 3.x with DefenseClaw |
| Dashboards | Grafana | [Grafana](https://github.com/grafana/grafana) (78k; v13.3.1, 2026-11-10); Perses | ~270 MiB | **Keep** |
| LLM tracing | Phoenix | [Phoenix](https://github.com/Arize-ai/phoenix) (12k, ELv2; v21.1.0, 2026-11-13); [Langfuse](https://github.com/langfuse/langfuse) (37k, MIT core; v4.80.0); Opik | Phoenix 1 container; Langfuse needs ClickHouse + Redis + S3 | **Keep** (license note §4) |
| Uptime | Gatus | [Gatus](https://github.com/TwiN/gatus) (13k; v5.38.0, 2026-10-28); Uptime Kuma (94k; UI config, not Git); blackbox_exporter | ~22 MiB | **Keep** |
| Push alerts | ntfy | [ntfy](https://github.com/binwiederhier/ntfy) (36k; v2.38.0, 2026-11-14); Gotify (no iOS app) | ~30 MiB | **Keep** |
| GPU metrics | dcgm-exporter | [dcgm-exporter](https://github.com/NVIDIA/dcgm-exporter) (1.9k; 4.9.0, 2026-11-06) | ~45 MiB | **Keep**, bump |
| Host audit | Lynis | [Lynis](https://github.com/CISOfy/lynis) (17k; 3.1.7, 2026-06-25); kube-bench (k8s) | on demand | **Keep** |
| Secret scanning | gitleaks + TruffleHog + Trivy | [Betterleaks](https://github.com/betterleaks/betterleaks) (3k, MIT; v1.10.1, 2026-11-12); gitleaks (31k; maintenance-only); [TruffleHog](https://github.com/trufflesecurity/trufflehog) (29k; v3.99.9) | CI | **Narrow** (§2.6); move to Betterleaks later |
| Vuln / SBOM | Trivy + OSV | [Trivy](https://github.com/aquasecurity/trivy) (39k; v0.76.2); [OSV-Scanner](https://github.com/google/osv-scanner) (12k; v2.7.1); [Grype](https://github.com/anchore/grype) + Syft | CI | **Keep** (digest-pinned) |
| SAST | Semgrep CE | Semgrep CE (18k; 1.185.0); [Opengrep](https://github.com/opengrep/opengrep) (3.3k, LGPL fork; v2.0.0, 2026-11-13); CodeQL (free for public repos only) | CI | **Keep**; Opengrep if rule licensing matters (§4) |
| Signing | cosign keyless | [cosign](https://github.com/sigstore/cosign) (6.4k; v3.1.4, 2026-10-20) | CI | **Keep** |
| AI security | DefenseClaw + Cisco scanners + Agentic Radar | [DefenseClaw](https://github.com/cisco-ai-defense/defenseclaw) (0.9k; 1.0.9, 2026-11-12); [mcp-scanner](https://github.com/cisco-ai-defense/mcp-scanner) (1.1k); [skill-scanner](https://github.com/cisco-ai-defense/skill-scanner) (2.7k); [a2a-scanner](https://github.com/cisco-ai-defense/a2a-scanner) (0.2k, last push 2026-04); [aibom](https://github.com/cisco-ai-defense/aibom) (0.1k; 1.10.1); [Agentic Radar](https://github.com/splx-ai/agentic-radar) (1.1k; v0.14.2) | DefenseClaw gateway 80–570 MiB | **Keep** (D7); watch a2a-scanner activity |
| Model gateway | LiteLLM | [LiteLLM](https://github.com/BerriAI/litellm) (63k; v1.109.1, 2026-11-12); Envoy AI Gateway; Portkey OSS gateway | LiteLLM ~1 GiB (4 workers) | **Keep** (MCP + A2A in one, D20); 2 workers would roughly halve memory if load allows |
| Serving | vLLM, llama.cpp via DGXMM | [vLLM](https://github.com/vllm-project/vllm) (97k); [llama.cpp](https://github.com/ggml-org/llama.cpp) (135k); SGLang | GPU | **Keep** |
| Chat UI | Open WebUI | [Open WebUI](https://github.com/open-webui/open-webui) (159k; v0.13.3, 2026-11-08); LibreChat (MIT) | ~50 MiB idle | **Keep** (license note §4) |
| Experiment tracking | MLflow | [MLflow](https://github.com/mlflow/mlflow) (29k; v3.18.0, 2026-11-04); Aim; W&B (SaaS, no) | ~55 MiB | **Keep** |
| Workflows | Temporal | [Temporal](https://github.com/temporalio/temporal) (24k; v1.32.2); [Argo Workflows](https://github.com/argoproj/argo-workflows) (17k; v4.1.6); [Hatchet](https://github.com/hatchet-dev/hatchet) (8.3k; v0.114.2); [Prefect](https://github.com/PrefectHQ/prefect) (24k; 3.9.3) | Temporal ~180 MiB idle | **Revisit at P6.6** (§2.10) |
| Simulation | Isaac Lab, MuJoCo | [Isaac Lab](https://github.com/isaac-sim/IsaacLab) (8.7k); [MuJoCo](https://github.com/google-deepmind/mujoco) (18k) | GB10 | **Keep** |
| Voice | LiveKit | [LiveKit](https://github.com/livekit/livekit) (22k; v1.13.11, 2026-10-25) | ~340 MiB | **Keep**; run non-`--dev` with a key file (F4) |
| Agents | Hermes, picoclaw | [hermes-agent](https://github.com/NousResearch/hermes-agent) (264k); [picoclaw](https://github.com/sipeed/picoclaw) (30k) | ~220 MiB per profile; ~30 MiB | **Keep** |
| Robotics transport | ROS 2 + rmw_zenoh | [Zenoh](https://github.com/eclipse-zenoh/zenoh) (3.3k); [rmw_zenoh](https://github.com/ros2/rmw_zenoh) (0.5k) | ~90 MiB router | **Keep** (D6) |
| Home | Home Assistant | [HA](https://github.com/home-assistant/core) (92k) | ~490 MiB | **Keep**, pin |
| PaaS | Coolify | [Coolify](https://github.com/coollabsio/coolify) (66k); Dokku; Argo CD | 177 MiB | **Retire** (§2.8) |
| Launcher | Homepage | [Homepage](https://github.com/gethomepage/homepage) (34k; v2.8.0); Grafana links; Glance | 113 MiB | **Retire later** (§2.12) |
| Backup | restic | [restic](https://github.com/restic/restic) (37k; v0.19.1); [Kopia](https://github.com/kopia/kopia) (15k; v0.23.1); Borg (14k; 1.4.5) | small | **Keep** |
| Postgres | CNPG | [CloudNativePG](https://github.com/cloudnative-pg/cloudnative-pg) (9.6k; v1.30.1, 2026-09-23) | operator 26 MiB | **Keep**, consolidate onto it |
| Object store | SeaweedFS (planned) | [SeaweedFS](https://github.com/seaweedfs/seaweedfs) (36k; 4.53, 2026-11-08); [RustFS](https://github.com/rustfs/rustfs) (36k, Apache-2.0; 1.0.6, 2026-11-15, young); Garage (AGPL); MinIO (community edition stripped down, avoid) | ~150–300 MiB (e) | **Keep plan**; RustFS is the one to watch |
| Cache | Redis 7.4 | [Valkey](https://github.com/valkey-io/valkey) (BSD-3); Redis 8 (AGPL option) | same | **Switch to Valkey** (§4) |

Nothing in the table is worth a wholesale switch for marginal gains. The only switches recommended are licence-driven
(Redis → Valkey) or removals.

---

## 4. Free-ness check

Legend: **OK** = OSI open source, self-hosted version fully featured for our use. **Note** = free for us but
source-available, feature-gated or dependent on a free external service. **Flag** = not open source, or a real risk
of stopping being free.

| Tool | License | Self-hosted fully free? | Paid dependency / risk | Verdict |
|---|---|---|---|---|
| k3s, Helm, Argo CD, KSOPS, kube-vip, CoreDNS, Kyverno, CNPG, kube-state-metrics | Apache-2.0 | Yes | None | OK |
| Ansible | GPL-3.0 | Yes (AWX/AAP not needed) | None | OK |
| SOPS / age | MPL-2.0 / BSD-3 | Yes | None | OK |
| Renovate | AGPL-3.0 | Yes; we use the free Mend-hosted app | Mend app could change; fallback: run the CLI in Actions or a CronJob | Note |
| Docker Engine / Compose | Apache-2.0 | Yes (Docker Desktop isn't used) | None | OK |
| Tailscale | Client BSD-3; control plane SaaS | Free **Personal** plan: unlimited user devices, **up to 6 users, 3 ACL groups, 50 tagged resources**, 1,000 ephemeral-node minutes/month ([pricing](https://tailscale.com/pricing), fetched 2026-11-15) | Family members count as users (6 max); tags fine for 5 hosts + future k8s operator proxies (watch the 50). Exit: [Headscale](https://github.com/juanfont/headscale) (BSD-3) | Note |
| Caddy, nginx, dnsmasq, UFW | Apache-2.0 / BSD-2 / GPL | Yes | None | OK |
| Pocket ID | BSD-2 | Yes | None | OK |
| oauth2-proxy | MIT | Yes | None | OK |
| NATS | Apache-2.0 | Yes (Synadia Cloud not needed) | None | OK |
| Mosquitto | EPL-2.0 / EDL-1.0 | Yes (Cedalo Pro not needed) | None | OK |
| EMQX (not used) | BSL 1.1 from 5.9 | Single node free in production | Not OSI | Flag (don't adopt) |
| OTel Collector | Apache-2.0 | Yes | None | OK |
| VictoriaMetrics, vmalert | Apache-2.0 | Yes for our use; **downsampling, multiple retentions, vmbackupmanager** are Enterprise | "1 year metrics" works without downsampling; just more disk | Note |
| Alertmanager, blackbox_exporter, node_exporter | Apache-2.0 | Yes | None | OK |
| Grafana, Loki, Tempo | AGPL-3.0 | Yes; Enterprise/Cloud not needed | AGPL obliges source release only if we modify and serve to others; we don't | OK (AGPL note) |
| **Arize Phoenix** | **Elastic License 2.0** | Yes, no feature gate for self-hosting | Can't be offered as a hosted service; not OSI; Arize could gate features behind its license-key mechanism later | **Flag (low)**: fine for personal use; Langfuse (MIT core) is the fallback |
| Gatus | Apache-2.0 | Yes | None | OK |
| ntfy | Apache-2.0 / GPL-2.0 | Yes | **iOS instant delivery uses `upstream-base-url: https://ntfy.sh`** (free public relay, poll requests only, no message content) | Note: if ntfy.sh ever limits it, iOS falls back to slower polling; Android/web unaffected |
| dcgm-exporter / DCGM | Apache-2.0 | Yes | NVIDIA driver (proprietary, free) | OK |
| jetson_stats (if added) | AGPL-3.0 | Yes | None | OK |
| Lynis | GPL-3.0 | Yes (Lynis Enterprise not needed) | None | OK |
| GitHub (repo, Actions, GHCR) | SaaS | Free plan: private-repo Actions minutes are limited, no required-check enforcement, no free arm64 hosted runners for private repos (decisions 0001, 0008) | Real lock-in is moderate: workflows are plain `docker run` steps, portable to Forgejo/Gitea Actions or the self-hosted runner | Note |
| gitleaks / Betterleaks | MIT | Yes | gitleaks maintenance-only | Note |
| TruffleHog | AGPL-3.0 | Yes (Enterprise not needed; `--only-verified` calls the providers' APIs) | None | OK |
| OSV-Scanner | Apache-2.0 | Yes | OSV.dev API (free, Google) | OK |
| Trivy | Apache-2.0 | Yes | Vuln DB downloaded from GHCR (free); March 2026 compromise (§2.6) | OK, keep digest pins |
| **Semgrep CE** | Engine LGPL-2.1; **`p/default` rules under the Semgrep Rules License v1.0** (internal use only, no redistribution; updated 2024-12-13, [terms](https://semgrep.dev/legal/rules-license)) | Yes for internal CI | Rules are not open source; Pro rules/engine are paid. Fallback: Opengrep with its open rules | **Flag (low)** |
| cosign keyless | Apache-2.0 | Yes | Public Sigstore (Fulcio, Rekor) is a free public-good service; outage = no signing that day | Note |
| actionlint, yamllint, ansible-lint, kubeconform, pytest | MIT / GPL / Apache | Yes | None | OK |
| DefenseClaw, mcp-scanner, skill-scanner, a2a-scanner, aibom | Apache-2.0 | Yes; the `ai-defense-*` integrations need a paid AI Defense tenant and aren't used (decision 0003) | Cisco could steer features toward the paid service; today everything used is local | OK (watch) |
| Agentic Radar | Apache-2.0 | Yes (SPLX, now part of Zscaler) | Vendor-owned project | OK (watch) |
| **LiteLLM** | MIT, except `enterprise/` (commercial) | Core gateway, virtual keys, budgets, rate limits, Admin UI, MCP gateway with per-key/team permissions, custom guardrails: free ([enterprise page](https://docs.litellm.ai/docs/enterprise), [MCP docs](https://docs.litellm.ai/docs/mcp)). **Enterprise-only:** SSO beyond **5 users**, **guardrails applied per key/team**, **audit logs**, JWT auth/RBAC/team admins, secret-manager integrations and automated key rotation, IP allowlists, tag-based budgets, several built-in guardrails (e.g. `llamaguard_moderations`, `hide_secrets`) | The design leans on per-agent policy (D20, §7.1). Per-key MCP permissions are free; **per-key guardrail config and LiteLLM audit logs are not**. Keep the DefenseClaw plugin global (it already decides per agent from the key's metadata) and keep the audit trail in DefenseClaw + Loki. Verify in the LiteLLM session (`/docs/mcp_control`) | **Flag (medium)** |
| **Redis 7.4.12** (LiteLLM, Coolify) | **RSALv2 / SSPLv1** (7.4–7.8); 8.x adds AGPLv3 ([Redis licenses](https://redis.io/legal/licenses/)) | Usable for free, **not open source** | `redis:7-alpine` silently moved us onto RSAL/SSPL | **Flag**: switch to Valkey (BSD-3), or `redis:8` under AGPL |
| PostgreSQL | PostgreSQL License | Yes | None | OK |
| vLLM, llama.cpp | Apache-2.0 / MIT | Yes | Model weights have their own licenses (D4 open) | Note |
| **Open WebUI** | **Open WebUI License**: BSD-3 plus a branding clause (no removing "Open WebUI" branding unless ≤50 users in 30 days, written permission or an enterprise license) ([LICENSE](https://github.com/open-webui/open-webui/blob/main/LICENSE)) | Yes | Not OSI since the 2025 relicense; harmless for us (we don't rebrand, far under 50 users). Could tighten again | **Flag (low)**; LibreChat (MIT) is the fallback |
| MLflow | Apache-2.0 | Yes (Databricks managed not needed) | None | OK |
| Temporal | MIT | Yes; OSS server is fully featured; Temporal Cloud is the paid option | None | OK |
| Isaac Lab | BSD-3 | Yes | **Isaac Sim / Omniverse Kit components and RTX rendering ship under NVIDIA licenses** (free, not open source); the "kitless" image avoids most of it | Note |
| MuJoCo, MJX, Playground, Brax, JAX | Apache-2.0 | Yes | None | OK |
| LiveKit | Apache-2.0 | Yes (LiveKit Cloud paid, not needed) | None | OK |
| Hermes, picoclaw | MIT | Yes | Hermes uses WhatsApp (Meta) as a channel | Note |
| ROS 2, rmw_zenoh, Zenoh | Apache-2.0 / EPL-2.0 | Yes (ZettaScale commercial support not needed) | None | OK |
| Home Assistant | Apache-2.0 | Yes; Nabu Casa cloud optional | None | OK |
| Coolify | Apache-2.0 | Yes (Coolify Cloud paid) | — | OK (retire anyway) |
| Homepage | GPL-3.0 | Yes | None | OK |
| restic, rest-server | BSD-2 | Yes | Off-site target (B2) would be paid beyond 10 GB; a USB drive is free | Note |
| SeaweedFS | Apache-2.0 | Yes; a separate SeaweedFS Enterprise edition exists (extra features, free below a capacity threshold) | We only need the OSS S3 gateway | Note |
| NVIDIA driver, CUDA, DGX OS, JetPack | Proprietary, free | Yes | Vendor platform; unavoidable on this hardware | Note |

**Nothing in use requires payment today.** The three flags to act on or accept: Redis (switch), LiteLLM enterprise
gating (design around it), Phoenix/Open WebUI/Semgrep rules (source-available; accept, with named fallbacks).

---

## 5. Recommendations summary

Memory figures are measured unless marked (e). Effort: S = under an hour, M = an evening, L = several sessions.

### 5.1 Do now

| # | Recommendation | Memory saved | Simplification | Effort | Decision? |
|---|---|---|---|---|---|
| 1 | **Finish the P3.3 edge cutover; retire `edge-caddy` (Docker), `nginx-gateway` and `edge-dnsmasq`** after porting nginx's `model.`/`ha.`/`voice-agent.` path routes into the k3s Caddy (§2.1, §2.15) | ~26 MiB | **Biggest**: front door fully in Git, 2 fewer hops, 1 DNS server, F6/F7 closed | M | Cutover timing |
| 2 | **Retire Coolify** (0 apps), with its Postgres 15 and Redis 7.4; export `/data/coolify` first (§2.8) | ~177 MiB on dgx-1 | 4 containers, 1 Postgres, 1 RSAL Redis, a Docker-socket holder and a route gone | S | **Yes** |
| 3 | **Replace LiteLLM's Redis 7.4 with Valkey** (pinned by digest), as part of moving LiteLLM into the repo (§4) | 0 | Licence back to BSD; one less "could stop being free" | S | No |
| 4 | **Move Cisco AIBOM image scans off the Jetson and Pi** (scan their images by digest from dgx-2; keep code scans light) (§2.7) | ~1.1 GiB peak on the Jetson | Removes the main nightly OOM risk on the tightest host | S–M | No |
| 5 | **One oauth2-proxy** behind Caddy `forward_auth` for every OIDC-less UI, and **Gatus native OIDC** (§2.2) | ~20 MiB | 3 → 1 proxy; new protected app = one Caddy line | M | No |
| 6 | **Narrow scanner scopes**: Trivy `fs --scanners vuln,misconfig`; add standalone shellcheck; keep digest pins (§2.6) | CI only | Fewer duplicate secret findings; closes the shell-script lint gap | S | No |
| 7 | **Pin and bring hand-run services into Git**: HA (`:stable`), LiveKit (`--dev`, F4), Open WebUI, LiteLLM; bump Pocket ID, dcgm-exporter, CoreDNS, Lynis (§2.17) | 0 | Renovate sees everything; no silent upgrades | M | No |

### 5.2 Consider later

| # | Recommendation | Memory saved | Simplification | Effort | Decision? |
|---|---|---|---|---|---|
| 8 | **Slim OTel Collector build** (OCB, only used components, `GOMEMLIMIT`) for the Pi, Dell and Jetson (§2.16) | ~100–150 MiB per small host (e), ~0.3–0.45 GiB total | Smaller attack surface; one more build artifact to maintain (sign it with `build-sign.yml`) | M | No |
| 9 | **One CNPG cluster** for LiteLLM, MLflow, Temporal (and agent memory) in P3.7 (§2.11) | ~50 MiB (e) | 4 → 1 Postgres, one backup/upgrade/HA path | L (planned) | No |
| 10 | **Temporal: don't migrate in P3.7; decide at P6.6** between Temporal and Argo Workflows; stop it until then if you like (§2.10) | 180 MiB while stopped | One less stateful service until it has a job | S now, M at P6.6 | **Yes** |
| 11 | **Retire Homepage** once Fleet Home (Grafana) or the console exists (§2.12) | ~126 MiB on the Dell (with its proxy) | One less app on the 8 GB host | S | **Yes** (when) |
| 12 | **One DefenseClaw gateway per host on the Jetson** instead of one per Hermes user, if per-user isolation isn't needed (§2.16) | ~0.3–0.4 GiB (e) | One gateway to watch | M | **Yes** (security boundary) |
| 13 | Fold the `ml-api` Caddy into the front door or a NetworkPolicy once sim jobs are pods (§2.2) | ~15 MiB | 1 fewer Caddy | S | No |
| 14 | Extend fleet-metrics with tegrastats for the Jetson instead of adding a jetson-stats exporter; fix architecture §13 (§2.9) | avoids ~50 MiB (e) | No new daemon | S | No |
| 15 | Swap gitleaks for Betterleaks once it has a pinnable image and a few more months of releases (§2.6) | CI only | Same job, maintained upstream | S | No |
| 16 | Tempo 3.x when DefenseClaw's bundle moves to it; hold the major in Renovate (§2.4) | ~0 | Stays on a supported line | M | No |
| 17 | restic to SeaweedFS S3 when backups go on; drop rest-server (§2.14) | ~4 MiB | One less service | S | Backups on (0002) |
| 18 | LiteLLM: try 2 workers instead of 4 if latency allows (§3) | ~0.5 GiB (e) | — | S | No |

### 5.3 Keep as is

k3s, Argo CD + KSOPS, Ansible, SOPS + age, Helm, Renovate, Kyverno, Tailscale, Caddy (front door + Fleet proxy),
CoreDNS, kube-vip, Pocket ID, NATS **and** Mosquitto, VictoriaMetrics + vmalert + Alertmanager, Loki, Tempo, Grafana,
Phoenix, Gatus, ntfy, dcgm-exporter, fleet-metrics, Lynis, TruffleHog, OSV-Scanner, Trivy, Semgrep CE, cosign,
the Cisco AI-security tools and DefenseClaw, LiteLLM, DGXMM + vLLM/llama.cpp, Open WebUI, MLflow, Isaac Lab,
MuJoCo, LiveKit, Hermes, picoclaw, ROS 2 + Zenoh, Home Assistant, restic, CNPG, SeaweedFS (planned).

### 5.4 Totals

- **Do now (1–7):** ~0.2 GiB steady on dgx-1, plus ~1.1 GiB of peak pressure removed from the Jetson; 8–9
  containers and one unmanaged config tree retired.
- **Consider later (8–18):** another ~1–1.7 GiB (e) across the fleet, mostly on the small hosts (Pi, Dell, Jetson),
  where it matters most.

### 5.5 Needs your decision

1. Retire Coolify (#2).
2. Temporal's future: keep for P6.6 or move to Argo Workflows; stop it until then? (#10)
3. When to retire Homepage (#11).
4. One DefenseClaw gateway per Jetson host vs one per Hermes user (#12).
5. Accept the source-available licences (Phoenix ELv2, Open WebUI branding clause, Semgrep rules) with the named
   fallbacks, or switch now (not recommended).
6. Edge cutover timing (#1); backups on (decision 0002) for #17.
