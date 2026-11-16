---
title: "LiteLLM"
description: "The model gateway on dgx-1: deployment (Ansible, pinned 1.109.1), keys in SOPS, routes, the DefenseClaw guardrail, traces to Phoenix."
---

LiteLLM is the OpenAI-compatible gateway in front of the models DGXMM serves (D4: agents call models through LiteLLM,
never directly). D20 makes it the future MCP and A2A gateway too. The operational runbook is `runbooks/litellm.md`
in the repo (keys, rotation, guardrail, Phoenix).

| | |
|---|---|
| Containers | `litellm-proxy` (`ghcr.io/berriai/litellm:v1.109.1`, by digest), `litellm-postgres` (`postgres:16-alpine`, by digest, 127.0.0.1:5432), `litellm-redis` (`redis:7-alpine` = 7.4, by digest, 127.0.0.1:6379), `litellm-defenseclaw-bridge` (socat) |
| Host | dgx-1; `hosts/stacks/litellm` deployed by `playbooks/litellm.yml` to `/opt/homelab/litellm` (since 2026-11-15; was hand-run from `~/litellm-setup`) |
| Port | 0.0.0.0:4000 |
| URLs | `http(s)://model.nghodki.ai/v1` (front door → 10.100.136.1:4000); `https://litellm-admin.nghodki.ai` (the admin UI) |
| Sign-in | API: LiteLLM virtual keys. Admin UI: front door sign-in, then Pocket ID SSO (client `litellm`, `admins` → `proxy_admin`); break-glass `/fallback/login` |
| Health | `curl -s http://127.0.0.1:4000/health/readiness` on dgx-1; Gatus `model.nghodki.ai (LiteLLM)` |
| Secrets | `secrets/litellm.enc.yaml`: master key, salt key (both rotated 2026-11-15), Postgres and UI passwords, the DefenseClaw gateway token, the Phoenix API key, and the values of the picoclaw, judge and AIBOM keys |
| Backups | restic on dgx-1: `pg_dump` before each run, and `/opt/homelab/litellm` |
| AIBOM | the `litellm-proxy` image and `/opt/homelab/litellm` are scanned nightly on dgx-1 |
| Tailscale | `tag:agent` and `tag:home` may reach dgx-1:4000; `tag:robot` may not |
| k3s target | `models`, 2 replicas, same `LITELLM_SALT_KEY` on both, Postgres on CNPG (P3.7) |

## Routes

All routes live in LiteLLM's database; DGXMM registers its on-demand models (`qwen3.8-27b`,
`qwen3-coder-30b-a3b-instruct-fp4`, `twil-8b`, `nanbeige4.3-33b-nvfp4`, `flint-nvfp4`). The first request starts the
model (about 4.5 minutes for `qwen3.8-27b`), then about 2 s per short answer. `qwen3.8-27b` is the default model of
every fleet LLM consumer (decision 0012). The two dead static routes (`qwen3.6-35b`, `whisper-large-v3-turbo`) were
removed on 2026-11-15 (P0.7). Aliases (`smart`, `guard`, …) wait for P2.0.

## Keys for scanners and judges

| Key | Models | Limits | Used by |
|---|---|---|---|
| `defenseclaw-jetson-judge` | `qwen3.8-27b` | 60 rpm, 6 in flight | DefenseClaw judge and skill-scanner LLM analyzer, both Jetson users |
| `defenseclaw-dgx1` | `qwen3.8-27b` | 20 rpm, 2 in flight | dgx-1 DefenseClaw judge |
| `cisco-aibom` | `qwen3.8-27b` | 10 rpm, 1 in flight | Cisco AIBOM agentic stage (every host) |
| `picoclaw-pi` | `qwen3.8-27b` | — | picoclaw (rotated 2026-11-15 after a leak) |

The on-demand routes have no price, so budgets stay at 0 spend; the rate limits are what bound a scanner.

## DefenseClaw guardrail (P2.4, on since 2026-11-15)

`hosts/files/litellm/defenseclaw_guardrail.py`, a global pre-call and pre-MCP-call guardrail (per-key guardrails are
a LiteLLM enterprise feature). Every chat prompt and every MCP tool call goes to dgx-1's DefenseClaw gateway
(`POST /api/v1/agent-gateway/hook`, `connectors.agent_gateway.enabled`, action mode). `block` → HTTP 400 with the
reason. A prompt without an answer runs (fail open, logged); an MCP tool call without one is refused (fail closed).
The judge and scanner keys are skipped (their prompts quote what they judge). DefenseClaw listens on loopback only;
a socat relay on the docker0 address (172.17.0.1:18970, not the LAN) lets the container reach it as
`host.docker.internal:18970`.

## Traces (P2.6, on since 2026-11-15)

LiteLLM's `arize_phoenix` callback sends a trace per request to Phoenix on dgx-2 (`http://192.168.86.36:6006`,
project `litellm`, system API key `litellm-dgx-1`): model, key alias, token counts, prompt and reply.

## Who called the model API

- **Spend logs** on the admin UI's Logs page: key alias and hash, user, team, model, tokens, status, client IP; no
  prompts; kept 30 days (LiteLLM's own cleanup).
- **Phoenix**, project `litellm`, by key alias (with prompts and replies).
- **The front door's access log** in Loki (`service=edge-caddy`).

The client IP is the front door's `X-Forwarded-For`; while the LAN Service uses `externalTrafficPolicy: Cluster` it is
a pod-network address (`10.42.x.x`), and direct callers on :4000 can forge it. Trust the key alias.

## Gotchas

- Bound on all interfaces: anything on the LAN can reach :4000 directly (keys are still required).
- `litellm-admin.nghodki.ai` goes through the front door, which family and guests may reach over Tailscale. Since
  2026-11-16 the door signs you in first (edge-auth, `admins`); the LiteLLM UI login follows.
- Redis stays 7.4 (RSALv2/SSPL, free for private use); the Valkey switch was declined.
