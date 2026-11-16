---
title: "LiteLLM"
description: "The model gateway on dgx-1: what it is, how it is reached, its state (hand-run, pinned 1.109.1), the DefenseClaw guardrail plugin, and what waits for the DGXMM session."
---

LiteLLM is the OpenAI-compatible gateway in front of the models DGXMM serves (D4: agents call models by LiteLLM alias,
never directly). D20 makes it the future MCP and A2A gateway too. It is **owned by the DGXMM/LiteLLM session**; this
page describes its role and interfaces only.

| | |
|---|---|
| Containers | `litellm-proxy` (`ghcr.io/berriai/litellm:v1.109.1`, pinned by digest since P0.13; was `main-latest` 1.100.0), `litellm-postgres` (16-alpine, 127.0.0.1:5432), `litellm-redis` (7-alpine, 127.0.0.1:6379) |
| Host | dgx-1, hand-run from `~/litellm-setup` (not in the repo) |
| Port | 0.0.0.0:4000 |
| URLs | `http(s)://model.nghodki.ai/v1` (front door → nginx-gateway → `litellm:4000`); `https://litellm-admin.nghodki.ai` (front door → 100.65.137.82:4000, the admin UI) |
| Sign-in | LiteLLM keys (13 keys reviewed and kept, P0.17); admin UI login. Pocket ID after the DGXMM session |
| Health | `curl -s http://127.0.0.1:4000/health/liveliness` on dgx-1; Gatus `model.nghodki.ai (LiteLLM)` |
| Secrets | master and salt keys are **not in SOPS yet** (P0.14) |
| Backups | `restic_backup_pre_commands` on dgx-1 dumps the DB (`docker exec litellm-postgres pg_dump ...`) before each backup |
| AIBOM | the `litellm-proxy` image and `~/litellm-setup` are scanned nightly on dgx-1 |
| Tailscale | `tag:agent` and `tag:home` may reach dgx-1:4000; `tag:robot` may not |
| k3s target | `models`, 2 replicas, same `LITELLM_SALT_KEY` on both, Postgres on CNPG (P3.7) |

## Routes and aliases

Which models and alias names to serve is **not decided** (D4, plan P2.0, "your decision"). The names in the
architecture (`smart`, `robot-fast`, `guard`, `coder`, `vision`, `big`, `embed`, `stt`, `tts`) are placeholders.
Today, clients use model names; Hermes's main profile uses `qwen3.8-27b`. P0.7 still has two dead routes to remove
(`qwen3.6-35b`, `whisper-large-v3-turbo`). DGXMM should register and remove routes itself (P2.8).

## DefenseClaw guardrail plugin (P2.4)

`hosts/files/litellm/defenseclaw_guardrail.py` is a custom LiteLLM guardrail that sends every chat prompt and every MCP
tool call to DefenseClaw's agent-gateway route (`POST /api/v1/agent-gateway/hook`) and enforces the answer: `block`
stops the call; `allow` and `alert` let it run. Fail modes: an MCP tool call without a usable answer is **refused**; a
chat prompt without one runs with a warning. 8 tests run in CI. It loads in LiteLLM 1.109.1 but is **not enabled**.

```yaml
# LiteLLM config, when enabled (from the module docstring)
guardrails:
  - guardrail_name: defenseclaw
    litellm_params:
      guardrail: defenseclaw_guardrail.DefenseClawGuardrail
      mode: [pre_call, pre_mcp_call]
      default_on: true
      api_base: os.environ/DEFENSECLAW_URL       # e.g. http://host.docker.internal:18970
      api_key: os.environ/DEFENSECLAW_TOKEN
```

## Waiting for the DGXMM session

- P0.14: rotate the master and salt keys into SOPS; remove the dead routes.
- P2.4 on; P2.6 LiteLLM → Phoenix traces; P1.11 DefenseClaw LLM judge through LiteLLM.
- P1.13 Pocket ID for the LiteLLM UI.
- P2.0 aliases, then P2.1–P2.3, P2.5, P2.7, P2.8.
- A dedicated virtual key for Cisco AIBOM's LLM enrichment.

## Gotchas

- Bound on all interfaces: anything on the LAN can reach :4000 directly.
- `litellm-admin.nghodki.ai` goes through the front door, which family and guests may reach over Tailscale; the admin
  UI login is the only gate.
- Don't restart or reconfigure it from this repo's work; coordinate with the DGXMM session.
