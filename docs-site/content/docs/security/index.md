---
title: Security and identity
description: The security layers of the fleet, which ones are live today, and where each is documented.
---

The design (docs/design.md §8, architecture §12) lists nine layers. This page says which are **live** on 2026-11-15,
which are **partial**, and which are **planned**.

| # | Layer | Live today | Planned / partial |
|---|---|---|---|
| 1 | Network | Tailscale policy with tags and tests ([Tailscale](../network/tailscale.md)); most internal ports bound to loopback or a LAN IP | CrowdSec on the proxy (not deployed); Temporal mTLS; Zenoh auth |
| 2 | Identity | Pocket ID passkeys for Grafana, Gatus, Phoenix, Homepage, Temporal UI, MLflow, Argo CD ([Pocket ID](identity.md)); per-user NATS accounts; per-device Fleet MQTT users | Per-agent LiteLLM keys and scopes (P4.4); Pocket ID for LiteLLM UI, DGXMM UI, Open WebUI |
| 3 | Supply chain (CI) | gitleaks, TruffleHog, Semgrep, OSV-Scanner, Trivy, kubeconform, Kyverno CLI, ansible-lint, mcp-scanner, skill-scanner, a2a-scanner, Agentic Radar, Cisco AIBOM; actions pinned by SHA, tools hash-locked ([Scanning](scanning.md)); our images built and signed with cosign keyless (`build-sign.yml`) | ModelScan for downloads (P2.5) |
| 4 | Admission (k3s) | Kyverno 1.20, 6 policies in **Enforce** incl. signed-image verification ([Kyverno](../platform/kyverno.md)) | make the GHCR packages public so signed images are admitted |
| 5 | Agent runtime | DefenseClaw 1.0.9 on both Jetson Hermes users (action mode, fail closed, `homelab` policy, MCP admission registry + nightly drift check), on dgx-1 (Fleet gateway), Edge Connector on the Pi ([DefenseClaw](defenseclaw.md)); robot safety governor ([Safety governor](../robotics/safety-governor.md)) | LiteLLM guardrail plugin (written, not enabled, P2.4); LLM judge via LiteLLM; HITL webhooks (dropped) |
| 6 | Host runtime | base and hardening roles, weekly Lynis with documented exceptions, index 65–72 ([Hardening](hardening.md)) | Tetragon (P3.6), kube-bench |
| 7 | Testing | — | promptfoo, garak, PyRIT on a self-hosted runner (P4.8) |
| 8 | Recovery | Git rebuild; age key offline copies ([SOPS](secrets.md)) | Backups are off by decision 0002 (but see [Backups](../operations/backups.md)) |
| 9 | Visibility | 19 DefenseClaw dashboards and its alert rules; Fleet and Edge alerts ([Dashboards](../observability/dashboards.md)) | — |

## Principles in practice

- **Fail closed for consequences.** Hermes tool calls fail closed when DefenseClaw is down. The Edge Connector runs
  in strict mode. The governor stops the robot when inputs go stale. Agents can latch the e-stop but never clear it.
- **Fail visible for the rest.** Chat prompts through the (future) LiteLLM guardrail run with a warning when DefenseClaw
  doesn't answer.
- **No plaintext secrets.** CI fails on a plaintext file in `secrets/` or a plaintext Secret in `cluster/`.
- **GitHub never gets in.** Argo CD polls; Ansible runs from dgx-1 (D15).

## Two CAs

There are two private CAs with different trust scopes. Mixing them up is the most likely security mistake here.
See [PKI](pki.md).
