# docs-site

Documentation for the homelab fleet, written as MDX so it reads on GitHub as Markdown and can later be built into a site
(Fumadocs or Nextra). Start at [content/docs/index.mdx](content/docs/index.mdx).

## Layout

```
docs-site/
├── README.md                    this file: layout, how to build, coverage checklist
└── content/docs/
    ├── meta.json                top-level navigation order
    ├── index.mdx                home page
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
    ├── decisions/               D1–D25 and 0001–0009, status, known limits, docs vs live state
    └── history/                 changelog from the PR list
```

Conventions:

- Each page has YAML frontmatter with `title` and `description`.
- Each folder has a `meta.json` (`title`, `pages` in order; `---Label---` entries are separators), the format Fumadocs
  reads.
- Plain MDX only: no imports, no custom components, no raw HTML. Diagrams are ```` ```mermaid ```` blocks (GitHub
  renders them; a site build needs a Mermaid plugin).
- Links between pages are relative file links with the extension (`../network/ports.mdx`, `../hosts/index.mdx`), so
  they work in GitHub's file view. A site build has to map them to routes (Fumadocs: a small remark plugin or its
  relative-link support; unverified which version handles it out of the box).
- Repo files are named by path in backticks (`hosts/playbooks/observe.yml`) rather than linked, so pages don't break when
  read outside the repo.
- Curly braces and angle brackets appear only inside code, because MDX treats `{` and `<` in prose as JSX.
- No secrets: pages name the SOPS file and key instead. Facts that couldn't be checked are marked "(unverified)".

## Building a site later (optional)

Nothing is built today. With Fumadocs (Next.js), roughly:

```bash
# on dgx-1, in a scratch folder outside the repo
npm create fumadocs-app@latest homelab-docs     # choose "Fumadocs MDX"
cd homelab-docs
rm -rf content/docs && ln -s ~/homelab/docs-site/content/docs content/docs
npm install mermaid && npm run dev              # then add a Mermaid component/remark plugin for ```mermaid blocks
```

The site could later be served behind the front door (for example `docs.nghodki.ai`, behind oauth2-proxy and Pocket
ID). Nextra works too: it reads `_meta` files instead of `meta.json`, so those would need converting.

## Keeping it current

- Change the docs in the same PR as the behaviour change.
- When a plan item finishes, update [decisions/status.mdx](content/docs/decisions/status.mdx).
- When a difference between the docs and the live state is fixed, remove it from
  [decisions/discrepancies.mdx](content/docs/decisions/discrepancies.mdx).
- Add new roles, playbooks, stacks, runbooks and decisions to the checklist below.

## Coverage checklist

Every role, playbook, stack, runbook and decision in the repo, and the page that covers it. Checked by script on
2026-11-15: every item below appears by name on its page.

### Roles (`hosts/roles/`, 25)

| Role | Page |
|---|---|
| `always_on` | [hosts/omarchy](content/docs/hosts/omarchy.mdx) |
| `base` | [security/hardening](content/docs/security/hardening.mdx) |
| `cisco_aibom` | [security/scanning](content/docs/security/scanning.mdx) |
| `compose_stack` | [platform/docker-stacks](content/docs/platform/docker-stacks.mdx) |
| `defenseclaw_aibom` | [security/defenseclaw](content/docs/security/defenseclaw.mdx) |
| `defenseclaw_fleet` | [security/defenseclaw](content/docs/security/defenseclaw.mdx) |
| `defenseclaw_gateway_env` | [security/defenseclaw](content/docs/security/defenseclaw.mdx) |
| `defenseclaw_policy` | [security/defenseclaw](content/docs/security/defenseclaw.mdx) |
| `edge_connector` | [security/edge-connector](content/docs/security/edge-connector.mdx) |
| `fleet_metrics` | [observability/index](content/docs/observability/index.mdx), [hosts/index](content/docs/hosts/index.mdx) |
| `hardening` | [security/hardening](content/docs/security/hardening.mdx) |
| `homelab_ca` | [security/pki](content/docs/security/pki.mdx) |
| `jetson_cdi` | [hosts/jetson](content/docs/hosts/jetson.mdx) |
| `k3s` | [platform/k3s](content/docs/platform/k3s.mdx) |
| `lynis` | [security/hardening](content/docs/security/hardening.mdx) |
| `mcp_drift` | [security/defenseclaw](content/docs/security/defenseclaw.mdx), [agents/cards-and-tools](content/docs/agents/cards-and-tools.mdx) |
| `otel_host_collector` | [observability/index](content/docs/observability/index.mdx) |
| `restic_backup` | [services/backup-server](content/docs/services/backup-server.mdx) |
| `restic_install` | [services/backup-server](content/docs/services/backup-server.mdx) |
| `restic_prune` | [services/backup-server](content/docs/services/backup-server.mdx) |
| `ros_lidar` | [robotics/ros-zenoh](content/docs/robotics/ros-zenoh.mdx) |
| `ros_zenoh_router` | [robotics/ros-zenoh](content/docs/robotics/ros-zenoh.mdx) |
| `safety_governor` | [robotics/safety-governor](content/docs/robotics/safety-governor.mdx) |
| `tailscale` | [network/tailscale](content/docs/network/tailscale.mdx), [security/hardening](content/docs/security/hardening.mdx) |
| `tailscale_serve` | [network/tailscale](content/docs/network/tailscale.mdx) |

### Playbooks (`hosts/playbooks/`, 22)

All are listed with their hosts and roles in [operations/deploy](content/docs/operations/deploy.mdx). Topic pages:

| Playbook | Page |
|---|---|
| `aibom.yml` | [security/scanning](content/docs/security/scanning.mdx) |
| `alerting.yml` | [services/gatus-ntfy](content/docs/services/gatus-ntfy.mdx) |
| `always-on.yml` | [hosts/omarchy](content/docs/hosts/omarchy.mdx) |
| `backups.yml` | [services/backup-server](content/docs/services/backup-server.mdx) |
| `bus.yml` | [services/nats](content/docs/services/nats.mdx) |
| `collectors.yml` | [observability/index](content/docs/observability/index.mdx) |
| `console.yml` | [services/pocket-id](content/docs/services/pocket-id.mdx) |
| `defenseclaw.yml` | [security/defenseclaw](content/docs/security/defenseclaw.mdx) |
| `edge-connector.yml` | [security/edge-connector](content/docs/security/edge-connector.mdx) |
| `fleet-metrics.yml` | [operations/deploy](content/docs/operations/deploy.mdx) |
| `fleet.yml` | [services/fleet-broker](content/docs/services/fleet-broker.mdx) |
| `gpu.yml` | [platform/docker-stacks](content/docs/platform/docker-stacks.mdx) |
| `hardening.yml` | [security/hardening](content/docs/security/hardening.mdx) |
| `jobs.yml` | [services/temporal](content/docs/services/temporal.mdx) |
| `k3s.yml` | [platform/k3s](content/docs/platform/k3s.mdx) |
| `lynis.yml` | [security/hardening](content/docs/security/hardening.mdx) |
| `ml.yml` | [services/mlflow](content/docs/services/mlflow.mdx) |
| `observe.yml` | [services/observe-stack](content/docs/services/observe-stack.mdx) |
| `ops.yml` | [services/homepage](content/docs/services/homepage.mdx) |
| `pki.yml` | [security/pki](content/docs/security/pki.mdx) |
| `robot.yml` | [robotics/ros-zenoh](content/docs/robotics/ros-zenoh.mdx), [robotics/safety-governor](content/docs/robotics/safety-governor.mdx) |
| `site.yml` | [security/hardening](content/docs/security/hardening.mdx) |

### Compose stacks (`hosts/stacks/`, 11)

| Stack | Page |
|---|---|
| `alerting` | [services/gatus-ntfy](content/docs/services/gatus-ntfy.mdx) |
| `backup` | [services/backup-server](content/docs/services/backup-server.mdx) |
| `bus` | [services/nats](content/docs/services/nats.mdx) |
| `console` | [services/pocket-id](content/docs/services/pocket-id.mdx) |
| `fleet` | [services/fleet-broker](content/docs/services/fleet-broker.mdx) |
| `gpu` | [platform/docker-stacks](content/docs/platform/docker-stacks.mdx) |
| `jobs` | [services/temporal](content/docs/services/temporal.mdx) |
| `ml` | [services/mlflow](content/docs/services/mlflow.mdx) |
| `observe` | [services/observe-stack](content/docs/services/observe-stack.mdx) |
| `ops` | [services/homepage](content/docs/services/homepage.mdx) |
| `sim` | [robotics/simulation](content/docs/robotics/simulation.mdx) |

Outside the repo: edge-gateway → [network/front-door](content/docs/network/front-door.mdx), LiteLLM →
[services/litellm](content/docs/services/litellm.mdx), Open WebUI, Coolify, Home Assistant, LiveKit/control center →
their service pages.

### Runbooks (`runbooks/`, 18 + README)

| Runbook | Page |
|---|---|
| `age-key.md` | [security/secrets](content/docs/security/secrets.mdx) |
| `aibom.md` | [security/scanning](content/docs/security/scanning.mdx) |
| `alerting.md` | [observability/alert-delivery](content/docs/observability/alert-delivery.mdx) |
| `argocd.md` | [platform/argocd](content/docs/platform/argocd.mdx) |
| `build-sign.md` | [platform/image-signing](content/docs/platform/image-signing.mdx) |
| `edge-connector.md` | [security/edge-connector](content/docs/security/edge-connector.mdx) |
| `hardening.md` | [security/hardening](content/docs/security/hardening.mdx) |
| `hermes-profiles.md` | [agents/hermes](content/docs/agents/hermes.mdx) |
| `k3s.md` | [platform/k3s](content/docs/platform/k3s.mdx) |
| `kyverno.md` | [platform/kyverno](content/docs/platform/kyverno.mdx) |
| `mcp-admission.md` | [security/defenseclaw](content/docs/security/defenseclaw.mdx), [agents/cards-and-tools](content/docs/agents/cards-and-tools.mdx) |
| `mlflow.md` | [services/mlflow](content/docs/services/mlflow.mdx) |
| `robot-ros.md` | [robotics/ros-zenoh](content/docs/robotics/ros-zenoh.mdx) |
| `robot-safety.md` | [robotics/safety-governor](content/docs/robotics/safety-governor.mdx) |
| `sign-in.md` | [security/identity](content/docs/security/identity.mdx) |
| `simulation.md` | [robotics/simulation](content/docs/robotics/simulation.mdx) |
| `temporal.md` | [services/temporal](content/docs/services/temporal.mdx) |
| `web-https.md` | [security/pki](content/docs/security/pki.mdx) |
| `README.md` (planned incident runbooks) | [operations/incidents](content/docs/operations/incidents.mdx) |

### Decisions

| Decision | Page |
|---|---|
| D1–D25 (`docs/design.md` §6) | [decisions/index](content/docs/decisions/index.mdx) |
| `0001-github-free-plan.md` | [development/rules](content/docs/development/rules.mdx), [decisions/index](content/docs/decisions/index.mdx) |
| `0002-backups-off-for-now.md` | [operations/backups](content/docs/operations/backups.mdx) |
| `0003-cisco-ai-defense-tools.md` | [security/scanning](content/docs/security/scanning.mdx), [decisions/index](content/docs/decisions/index.mdx) |
| `0004-openbot-licensing.md` | [agents/openbot](content/docs/agents/openbot.mdx) |
| `0005-k3s-over-wifi.md` | [platform/k3s](content/docs/platform/k3s.mdx) |
| `0006-gitops-platform.md` | [platform/argocd](content/docs/platform/argocd.mdx) |
| `0008-image-signing.md` | [platform/image-signing](content/docs/platform/image-signing.mdx) |
| `0009-no-services-box.md` | [operations/incident-gpu-oom](content/docs/operations/incident-gpu-oom.mdx), [decisions/index](content/docs/decisions/index.mdx) |
| `0000-template.md` | [decisions/index](content/docs/decisions/index.mdx) |

### Other repo areas

| Area | Page |
|---|---|
| `cluster/` (bootstrap, platform, apps) | [platform/argocd](content/docs/platform/argocd.mdx), [network/cluster-network](content/docs/network/cluster-network.mdx) |
| `identity/pocket-id.yaml` | [security/identity](content/docs/security/identity.mdx) |
| `policies/tailscale/policy.hujson` | [network/tailscale](content/docs/network/tailscale.mdx) |
| `policies/defenseclaw/` | [security/defenseclaw](content/docs/security/defenseclaw.mdx) (`homelab.yaml`, `mcp-servers.yaml`), [security/edge-connector](content/docs/security/edge-connector.mdx) (`edge/fleet-1-1.yaml`) |
| `policies/kyverno/` | [platform/kyverno](content/docs/platform/kyverno.mdx) |
| `agents/`, `tools/` | [agents/cards-and-tools](content/docs/agents/cards-and-tools.mdx) |
| `robots/` | [robotics](content/docs/robotics/index.mdx) |
| `models/` | [agents/model-plane](content/docs/agents/model-plane.mdx) |
| `secrets/`, `.sops.yaml` | [security/secrets](content/docs/security/secrets.mdx) |
| `.github/workflows/`, `.github/scripts/` | [development/ci](content/docs/development/ci.mdx) |
| `renovate.json` | [operations/upgrades](content/docs/operations/upgrades.mdx) |
| `docs/upstream-issues/` | [decisions/known-limits](content/docs/decisions/known-limits.mdx) |
| `docs/model-supply-chain.md` | [agents/model-plane](content/docs/agents/model-plane.mdx) |
| `hosts/files/` (fleet-metrics, LiteLLM guardrail, Pocket ID sync, PKI, web CA) | [development/index](content/docs/development/index.mdx) |
