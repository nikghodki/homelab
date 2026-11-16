# homelab

Configuration, policies and docs for the home AI fleet: two DGX Sparks, a Jetson Orin, a Raspberry Pi and an
x86 laptop running Omarchy. Everything that runs on the fleet is described here. Changes go through pull requests
and CI, and are applied from inside the home network (Argo CD pulls this repo; Ansible runs from home). GitHub never
gets access into the network.

## Docs

| Document | Covers |
|---|---|
| [docs/design.md](docs/design.md) | Purpose, requirements, decisions D1–D27, risks, open questions |
| [docs/architecture.md](docs/architecture.md) | Components, network, cluster, model/tool/agent planes, robotics, security, observability, operations |
| [docs/project-plan.md](docs/project-plan.md) | Phases, tasks, acceptance checks, milestones |
| [docs-site/](docs-site/README.md) | Operator documentation (MDX): every host, service, network path, runbook and decision, with status and known differences from the live state |

## Layout

| Folder | Holds | Applied by |
|---|---|---|
| `hosts/` | Ansible inventory and roles for every device (OS hardening, Tailscale, DefenseClaw, collectors) | Ansible, from home |
| `cluster/` | k3s applications | Argo CD |
| `models/` | DGXMM catalog: model, alias, mode | DGXMM |
| `agents/` | One folder per agent: card, scopes, budget, DefenseClaw route | CI generates keys and permissions |
| `tools/` | Approved MCP servers, with their tool definitions and scan results | LiteLLM MCP gateway |
| `policies/` | DefenseClaw policies, Kyverno rules, Tailscale ACL, NATS accounts | Each system |
| `robots/` | Robot descriptions, tasks, policies, safety limits, Zenoh config | Ansible / training jobs |
| `secrets/` | Secrets encrypted with SOPS + age (never plaintext) | Decrypted only inside the home network |
| `runbooks/` | What to do when something breaks | People and the ops agent |
| `decisions/` | Decisions made after the design doc | — |

## How a change gets in

1. Open a pull request.
2. CI runs (see [.github/workflows](.github/workflows)):
   - lint
   - secret scanning
   - code, dependency and configuration scanning
   - Kubernetes manifest checks
   - DefenseClaw/Cisco AI scanners for MCP tools and skills
3. Merge when everything is green.
4. Argo CD and Ansible apply it at home.

## Rules

- Only `nikghodki` commits and pushes here, with the `92228606+nikghodki@users.noreply.github.com` identity.
- No plaintext secrets: anything under `secrets/` must be SOPS-encrypted (CI checks).
- Third-party tools run in CI as container images pinned by digest; GitHub actions are pinned to commit SHAs.
  Renovate proposes updates.
