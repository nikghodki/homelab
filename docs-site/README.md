# docs-site

Documentation for the homelab fleet, built with **MkDocs Material** and served privately at
**https://docs.nghodki.ai** (the Dell, behind oauth2-proxy and Pocket ID, `admins` only; never GitHub Pages). The pages
are plain Markdown, so they also read on GitHub. Start at [content/docs/index.md](content/docs/index.md). How it's
built, hosted, updated and rolled back, and how to add a page: `runbooks/docs-site.md`.

## Layout

```
docs-site/
├── README.md                    this file: layout, conventions, coverage checklist (not part of the site)
├── mkdocs.yml                   site config: Material theme, extensions, strict link/anchor validation, nav:
├── requirements-docs.txt        MkDocs, Material, pymdown-extensions, pinned with hashes
├── hooks/mermaid.py             serves a pinned, integrity-checked mermaid.min.js from the site (no CDN)
└── content/docs/
    ├── index.md                 home page
    ├── overview/                what the fleet is, main flows, glossary
    ├── hosts/                   one page per host (dgx-1, dgx-2, jetson, pi, omarchy, macbook-air)
    ├── network/                 LAN, Tailscale, DNS, front door routes, cluster networking, ports
    ├── security/                PKI, SOPS/age, Pocket ID, DefenseClaw, Edge Connector, scanning, hardening
    ├── observability/           pipeline, dashboards, alert rules, Gatus, alert delivery, failure scenarios
    ├── platform/                k3s, Argo CD, Kyverno, CNPG, Docker stacks, image signing
    ├── services/                one page per service
    ├── agents/                  Hermes, picoclaw, model plane, agent cards and MCP tools, OpenBot
    ├── robotics/                ROS 2 and Zenoh, safety governor, simulation
    ├── operations/              day one, deploying, how to add things, rotation, upgrades, backups, incidents, FAQ
    ├── development/             repo layout, CI, PR and identity rules
    ├── decisions/               D1–D27 and 0001–0010, status, known limits, docs vs live state
    └── history/                 changelog from the PR list
```

Conventions:

- Each page has YAML frontmatter with `title` (the page's H1 and nav label) and `description`; no H1 in the body.
- Navigation is `nav:` in `mkdocs.yml`: the tabs are Start here, Security, Running it, Building it; each folder is a
  section with its `index.md` first. A page missing from `nav:` fails the strict build.
- Links between pages are relative file links with the extension (`../network/ports.md`, `../hosts/index.md`), so
  they work on GitHub and on the site; `mkdocs build --strict` checks every link and anchor (CI job `docs`).
- Repo files are named by path in backticks (`hosts/playbooks/observe.yml`) rather than linked, so pages don't break
  outside the repo.
- Diagrams are ```` ```mermaid ```` blocks. Admonitions, tabs, details and code copy buttons are available.
- Python-Markdown rules: a blank line before every list; nested lists and blocks inside list items indented 4 spaces.
- Nothing loads from other hosts: system fonts, local search, Mermaid from the site.
- No secrets: pages name the SOPS file and key instead. Facts that couldn't be checked are marked "(unverified)".

## Build locally

```bash
# on dgx-1, from the repo root
python3 -m venv ~/.venvs/docs && ~/.venvs/docs/bin/pip install --require-hashes -r docs-site/requirements-docs.txt
NO_MKDOCS_2_WARNING=1 ~/.venvs/docs/bin/mkdocs build --strict -f docs-site/mkdocs.yml -d /tmp/docs-site
```

## Keeping it current

- Change the docs in the same PR as the behaviour change. After the merge the site updates within 15 minutes.
- When a plan item finishes, update [decisions/status.md](content/docs/decisions/status.md).
- When a difference between the docs and the live state is fixed, remove it from
  [decisions/discrepancies.md](content/docs/decisions/discrepancies.md).
- Add new roles, playbooks, stacks, runbooks and decisions to the checklist below.

## Coverage checklist

Every role, playbook, stack, runbook and decision in the repo, and the page that covers it. Checked by script on
2026-11-15: every item below appears by name on its page.

### Roles (`hosts/roles/`, 27)

| Role | Page |
|---|---|
| `always_on` | [hosts/omarchy](content/docs/hosts/omarchy.md) |
| `base` | [security/hardening](content/docs/security/hardening.md) |
| `cisco_aibom` | [security/scanning](content/docs/security/scanning.md) |
| `compose_stack` | [platform/docker-stacks](content/docs/platform/docker-stacks.md) |
| `defenseclaw_aibom` | [security/defenseclaw](content/docs/security/defenseclaw.md) |
| `defenseclaw_fleet` | [security/defenseclaw](content/docs/security/defenseclaw.md) |
| `defenseclaw_gateway_env` | [security/defenseclaw](content/docs/security/defenseclaw.md) |
| `defenseclaw_policy` | [security/defenseclaw](content/docs/security/defenseclaw.md) |
| `docs_site` | [services/docs-site](content/docs/services/docs-site.md) |
| `edge_connector` | [security/edge-connector](content/docs/security/edge-connector.md) |
| `fleet_metrics` | [observability/index](content/docs/observability/index.md), [hosts/index](content/docs/hosts/index.md) |
| `hardening` | [security/hardening](content/docs/security/hardening.md) |
| `homelab_ca` | [security/pki](content/docs/security/pki.md) |
| `jetson_cdi` | [hosts/jetson](content/docs/hosts/jetson.md) |
| `k3s` | [platform/k3s](content/docs/platform/k3s.md) |
| `lynis` | [security/hardening](content/docs/security/hardening.md) |
| `mcp_drift` | [security/defenseclaw](content/docs/security/defenseclaw.md), [agents/cards-and-tools](content/docs/agents/cards-and-tools.md) |
| `otel_host_collector` | [observability/index](content/docs/observability/index.md) |
| `picoclaw` | [agents/picoclaw](content/docs/agents/picoclaw.md) |
| `restic_backup` | [services/backup-server](content/docs/services/backup-server.md) |
| `restic_install` | [services/backup-server](content/docs/services/backup-server.md) |
| `restic_prune` | [services/backup-server](content/docs/services/backup-server.md) |
| `ros_lidar` | [robotics/ros-zenoh](content/docs/robotics/ros-zenoh.md) |
| `ros_zenoh_router` | [robotics/ros-zenoh](content/docs/robotics/ros-zenoh.md) |
| `safety_governor` | [robotics/safety-governor](content/docs/robotics/safety-governor.md) |
| `tailscale` | [network/tailscale](content/docs/network/tailscale.md), [security/hardening](content/docs/security/hardening.md) |
| `tailscale_serve` | [network/tailscale](content/docs/network/tailscale.md) |

### Playbooks (`hosts/playbooks/`, 22)

All are listed with their hosts and roles in [operations/deploy](content/docs/operations/deploy.md). Topic pages:

| Playbook | Page |
|---|---|
| `aibom.yml` | [security/scanning](content/docs/security/scanning.md) |
| `alerting.yml` | [services/gatus-ntfy](content/docs/services/gatus-ntfy.md) |
| `always-on.yml` | [hosts/omarchy](content/docs/hosts/omarchy.md) |
| `backups.yml` | [services/backup-server](content/docs/services/backup-server.md) |
| `bus.yml` | [services/nats](content/docs/services/nats.md) |
| `collectors.yml` | [observability/index](content/docs/observability/index.md) |
| `console.yml` | [services/pocket-id](content/docs/services/pocket-id.md) |
| `defenseclaw.yml` | [security/defenseclaw](content/docs/security/defenseclaw.md) |
| `edge-connector.yml` | [security/edge-connector](content/docs/security/edge-connector.md) |
| `fleet-metrics.yml` | [operations/deploy](content/docs/operations/deploy.md) |
| `fleet.yml` | [services/fleet-broker](content/docs/services/fleet-broker.md) |
| `gpu.yml` | [platform/docker-stacks](content/docs/platform/docker-stacks.md) |
| `hardening.yml` | [security/hardening](content/docs/security/hardening.md) |
| `jobs.yml` | [services/temporal](content/docs/services/temporal.md) |
| `k3s.yml` | [platform/k3s](content/docs/platform/k3s.md) |
| `lynis.yml` | [security/hardening](content/docs/security/hardening.md) |
| `ml.yml` | [services/mlflow](content/docs/services/mlflow.md) |
| `observe.yml` | [services/observe-stack](content/docs/services/observe-stack.md) |
| `ops.yml` | [services/homepage](content/docs/services/homepage.md), [services/docs-site](content/docs/services/docs-site.md) |
| `pki.yml` | [security/pki](content/docs/security/pki.md) |
| `robot.yml` | [robotics/ros-zenoh](content/docs/robotics/ros-zenoh.md), [robotics/safety-governor](content/docs/robotics/safety-governor.md) |
| `site.yml` | [security/hardening](content/docs/security/hardening.md) |

### Compose stacks (`hosts/stacks/`, 11)

| Stack | Page |
|---|---|
| `alerting` | [services/gatus-ntfy](content/docs/services/gatus-ntfy.md) |
| `backup` | [services/backup-server](content/docs/services/backup-server.md) |
| `bus` | [services/nats](content/docs/services/nats.md) |
| `console` | [services/pocket-id](content/docs/services/pocket-id.md) |
| `fleet` | [services/fleet-broker](content/docs/services/fleet-broker.md) |
| `gpu` | [platform/docker-stacks](content/docs/platform/docker-stacks.md) |
| `jobs` | [services/temporal](content/docs/services/temporal.md) |
| `ml` | [services/mlflow](content/docs/services/mlflow.md) |
| `observe` | [services/observe-stack](content/docs/services/observe-stack.md) |
| `ops` | [services/homepage](content/docs/services/homepage.md), [services/docs-site](content/docs/services/docs-site.md) |
| `sim` | [robotics/simulation](content/docs/robotics/simulation.md) |

Outside the repo: edge-gateway (rollback and nginx-gateway relay since the P3.3 cutover) → [network/front-door](content/docs/network/front-door.md), LiteLLM →
[services/litellm](content/docs/services/litellm.md), Open WebUI, Home Assistant, LiveKit/control center →
their service pages.

### Runbooks (`runbooks/`, 20 + README)

| Runbook | Page |
|---|---|
| `age-key.md` | [security/secrets](content/docs/security/secrets.md) |
| `aibom.md` | [security/scanning](content/docs/security/scanning.md) |
| `alerting.md` | [observability/alert-delivery](content/docs/observability/alert-delivery.md) |
| `argocd.md` | [platform/argocd](content/docs/platform/argocd.md) |
| `build-sign.md` | [platform/image-signing](content/docs/platform/image-signing.md) |
| `docs-site.md` | [services/docs-site](content/docs/services/docs-site.md), [development/index](content/docs/development/index.md) |
| `edge-connector.md` | [security/edge-connector](content/docs/security/edge-connector.md) |
| `edge.md` | [network/front-door](content/docs/network/front-door.md) |
| `hardening.md` | [security/hardening](content/docs/security/hardening.md) |
| `hermes-profiles.md` | [agents/hermes](content/docs/agents/hermes.md) |
| `k3s.md` | [platform/k3s](content/docs/platform/k3s.md) |
| `kyverno.md` | [platform/kyverno](content/docs/platform/kyverno.md) |
| `mcp-admission.md` | [security/defenseclaw](content/docs/security/defenseclaw.md), [agents/cards-and-tools](content/docs/agents/cards-and-tools.md) |
| `mlflow.md` | [services/mlflow](content/docs/services/mlflow.md) |
| `robot-ros.md` | [robotics/ros-zenoh](content/docs/robotics/ros-zenoh.md) |
| `robot-safety.md` | [robotics/safety-governor](content/docs/robotics/safety-governor.md) |
| `sign-in.md` | [security/identity](content/docs/security/identity.md) |
| `simulation.md` | [robotics/simulation](content/docs/robotics/simulation.md) |
| `temporal.md` | [services/temporal](content/docs/services/temporal.md) |
| `web-https.md` | [security/pki](content/docs/security/pki.md) |
| `README.md` (planned incident runbooks) | [operations/incidents](content/docs/operations/incidents.md) |

### Decisions

| Decision | Page |
|---|---|
| D1–D27 (`docs/design.md` §6) | [decisions/index](content/docs/decisions/index.md) |
| `0001-github-free-plan.md` | [development/rules](content/docs/development/rules.md), [decisions/index](content/docs/decisions/index.md) |
| `0002-backups-off-for-now.md` | [operations/backups](content/docs/operations/backups.md) |
| `0003-cisco-ai-defense-tools.md` | [security/scanning](content/docs/security/scanning.md), [decisions/index](content/docs/decisions/index.md) |
| `0004-openbot-licensing.md` | [agents/openbot](content/docs/agents/openbot.md) |
| `0005-k3s-over-wifi.md` | [platform/k3s](content/docs/platform/k3s.md) |
| `0006-gitops-platform.md` | [platform/argocd](content/docs/platform/argocd.md) |
| `0007-edge-in-cluster.md` | [decisions/index](content/docs/decisions/index.md), [network/front-door](content/docs/network/front-door.md) |
| `0008-image-signing.md` | [platform/image-signing](content/docs/platform/image-signing.md) |
| `0009-no-services-box.md` | [operations/incident-gpu-oom](content/docs/operations/incident-gpu-oom.md), [decisions/index](content/docs/decisions/index.md) |
| `0010-retire-coolify.md` | [decisions/index](content/docs/decisions/index.md) |
| `0000-template.md` | [decisions/index](content/docs/decisions/index.md) |

### Other repo areas

| Area | Page |
|---|---|
| `cluster/` (bootstrap, platform, apps) | [platform/argocd](content/docs/platform/argocd.md), [network/cluster-network](content/docs/network/cluster-network.md) |
| `identity/pocket-id.yaml` | [security/identity](content/docs/security/identity.md) |
| `policies/tailscale/policy.hujson` | [network/tailscale](content/docs/network/tailscale.md) |
| `policies/defenseclaw/` | [security/defenseclaw](content/docs/security/defenseclaw.md) (`homelab.yaml`, `mcp-servers.yaml`), [security/edge-connector](content/docs/security/edge-connector.md) (`edge/fleet-1-1.yaml`) |
| `policies/kyverno/` | [platform/kyverno](content/docs/platform/kyverno.md) |
| `agents/`, `tools/` | [agents/cards-and-tools](content/docs/agents/cards-and-tools.md) |
| `robots/` | [robotics](content/docs/robotics/index.md) |
| `models/` | [agents/model-plane](content/docs/agents/model-plane.md) |
| `secrets/`, `.sops.yaml` | [security/secrets](content/docs/security/secrets.md) |
| `.github/workflows/`, `.github/scripts/` | [development/ci](content/docs/development/ci.md) |
| `renovate.json` | [operations/upgrades](content/docs/operations/upgrades.md) |
| `docs/upstream-issues/` | [decisions/known-limits](content/docs/decisions/known-limits.md) |
| `docs/model-supply-chain.md` | [agents/model-plane](content/docs/agents/model-plane.md) |
| `hosts/files/` (fleet-metrics, LiteLLM guardrail, Pocket ID sync, PKI, web CA) | [development/index](content/docs/development/index.md) |
