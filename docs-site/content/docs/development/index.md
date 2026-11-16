---
title: Repo layout
description: What lives where in nikghodki/homelab and who applies each folder.
---

`github.com/nikghodki/homelab`, private, squash-only merges, GitHub Free (decision 0001). Clone on dgx-1 at `~/homelab`.

| Folder | Holds | Applied by |
|---|---|---|
| `docs/` | `design.md` (D1–D27), `architecture.md`, `project-plan.md` (status in §2a), `model-supply-chain.md`, `reviews/` (code review 2026-11-15, tool review 2026-11), `upstream-issues/` (8 drafts, not posted) | people |
| `docs-site/` | this documentation (MkDocs Material), served privately at https://docs.nghodki.ai (behind Pocket ID, admins) from the Dell, rebuilt by a systemd timer every 15 min; runbook `runbooks/docs-site.md` | people, the Dell's timer |
| `decisions/` | decision records 0001–0010, `0000-template.md` | people |
| `runbooks/` | how-tos: age key, AIBOM, alerting, Argo CD, build-sign, docs site, edge (the front door in k3s), Edge Connector, hardening, Hermes profiles, k3s, Kyverno, MCP admission, MLflow, robot ROS, robot safety, sign-in, simulation, Temporal, web HTTPS | people |
| `hosts/` | Ansible: `inventory.yml`, `group_vars/`, `host_vars/`, `playbooks/` (22), `roles/` (26), `stacks/` (11 Compose stacks), `files/` (fleet-metrics, LiteLLM guardrail, Pocket ID sync, PKI certs, web CA page) | Ansible from dgx-1 |
| `cluster/` | `bootstrap/apps/` (app of apps), `platform/` (argocd, kyverno, cnpg-operator, cluster-dns, kube-vip, edge, kube-state-metrics), `apps/` (`_smoke`) | Argo CD |
| `policies/` | `defenseclaw/` (fleet policy, MCP server registry `mcp-servers.yaml`, edge policy, tests), `kyverno/` (5 ValidatingPolicies + 1 ImageValidatingPolicy), `tailscale/policy.hujson` | Ansible, Argo CD, the Tailscale console |
| `identity/` | `pocket-id.yaml` (groups, users, OIDC clients) | `pocketid_sync.py` |
| `secrets/` | SOPS-encrypted files only (12 + README) | decrypted on dgx-1 / by KSOPS |
| `agents/` | `hermes/card.yaml` (A2A card) | CI scanners |
| `tools/` | approved MCP servers: `picoclaw_only/`, `homeassistant/` (`server.yaml`, `tools.json`, `tools.sha256`) | CI scanners |
| `robots/` | `safety/` (limits + governor code and tests), `sim/` (Isaac Lab README, MuJoCo image, `measure.sh`) | Ansible, by hand |
| `models/` | DGXMM catalog: empty (aliases undecided, P2.0) | DGXMM (later) |
| `reports/` | CI report output (Agentic Radar) | CI |
| `.github/` | `workflows/` (pr-checks, nightly-scan, build-sign), `scripts/` (checks and scanners + tests), hash-locked requirements, `osv-scanner.toml`, PR template | GitHub Actions |
| root | `README.md`, `renovate.json`, `.sops.yaml`, `.yamllint.yaml`, `.editorconfig`, `.gitignore`, `LICENSE` | — |

## Code in the repo (all tested in CI)

| Code | Language | Tests |
|---|---|---|
| `hosts/files/fleet-metrics/` (agent on every host) | Python stdlib | `pytest` (collect, server, services, fixtures) |
| `hosts/files/litellm/defenseclaw_guardrail.py` | Python (httpx) | 10 tests |
| `hosts/files/pocket-id/pocketid_sync.py` | Python (httpx, yaml) | tests |
| `hosts/roles/cisco_aibom/files/cisco-aibom-fleet.py` | Python | tests |
| `hosts/roles/mcp_drift/files/mcp-drift.py` | Python (yaml) | tests |
| `robots/sim/isaaclab/train_mlflow.py` | Python | — |
| `hosts/roles/defenseclaw_aibom/files/homelab-aibom.py` | Python | — |
| `hosts/roles/restic_backup/files/sqlite-snapshot.py` | Python | — |
| `robots/safety/governor/` | Python (rclpy, nats-py) | core and sinks tests; on-Pi integration test |
| `robots/safety/motion_bridge/` | Python (rclpy) | core tests; on-Pi motion integration test |
| `hosts/roles/picoclaw/files/` (`governor-motion.js`, the MCP patch, `picoclaw_paths.py`) | JS, patch, Python | via the motion integration test |
| `robots/sim/mujoco/train_ppo.py`, `robots/sim/measure.sh` | Python, bash | — |
| `.github/scripts/*` | Python, bash | `defenseclaw-bundle`, `mcp-tool-hashes` tests |
| `policies/defenseclaw/tests/` | pytest | the policy can't be loosened |

The PR template asks: secrets encrypted? scopes minimal? safety limits unchanged or explained? docs/runbooks updated?
