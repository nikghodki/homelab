---
title: "LiteLLM"
description: "The model gateway, in k3s since 2026-11-16 (2 replicas, Postgres on CNPG): addresses, callers, relays on dgx-1, keys in SOPS, routes, the DefenseClaw guardrail, traces to Phoenix."
---

LiteLLM is the OpenAI-compatible gateway in front of the models DGXMM serves (D4: agents call models through LiteLLM,
never directly). D20 makes it the future MCP and A2A gateway too. The operational runbook is `runbooks/litellm.md`
in the repo (keys, rotation, guardrail, Phoenix).

| | |
|---|---|
| Runs as | k3s since 2026-11-16 (P3.7): namespace `litellm`, Argo CD app `litellm` (`cluster/apps/litellm`). The proxy (`ghcr.io/berriai/litellm:v1.109.1`, by digest) with **2 replicas, one per Spark**, and Redis 7.4 (1 replica) |
| Addresses | fixed ClusterIPs: proxy `10.43.0.150:4000` (`litellm/litellm`), Redis `10.43.0.152:6379`. Nothing listens on the LAN or the tailnet any more |
| Database | CNPG `data/litellm-db` (Argo CD app `data`): Postgres 17.12, primary on dgx-2, standby on dgx-1; the primary at `10.43.0.151:5432` ([CloudNativePG](../platform/cnpg.md)) |
| URLs | `http(s)://model.nghodki.ai/v1` and `https://litellm-admin.nghodki.ai` (the admin UI): front door → `10.43.0.150:4000` first, the stopped Docker copy (`10.100.136.1:4000`) only while the pods' health check fails, until 2026-11-23 |
| Coding tools | Claude Code, Codex and the Claude Code extension in Cursor on a Mac: [Use the home models in Claude Code, Cursor and Codex](../agents/coding-tools.md) (keys `claude-code`, `codex`) |
| Callers | everything through the front door, except Open WebUI (`http://10.43.0.150:4000/v1`, stored in its database) and DGXMM's route sync (`10.43.0.150:4000`); the ops agent should use the ClusterIP too |
| Relays on dgx-1 | `hosts/stacks/litellm-bridges` (`playbooks/litellm-bridges.yml`, socat): DGXMM's on-demand gateway on `10.100.136.1:8091`, the DefenseClaw gateway on `10.100.136.1:18970`; **until 2026-11-23** transition relays on `127.0.0.1:4000` and `10.100.136.1:4000` → `10.43.0.150:4000` for callers still on the old addresses |
| Sign-in | API: LiteLLM virtual keys. Admin UI: front door sign-in, then Pocket ID SSO (client `litellm`, `admins` → `proxy_admin`); break-glass `/fallback/login` |
| Health | `kubectl -n litellm get pods`; `curl -s 10.43.0.150:4000/health/readiness` from a Spark (`db: connected`); Gatus `model.nghodki.ai (LiteLLM)` |
| Secrets | `secrets/litellm.enc.yaml`: master key, salt key (both rotated 2026-11-15), database, Redis and UI passwords, the DefenseClaw gateway token, the Phoenix API key, and the values of the picoclaw, judge and AIBOM keys. Built into the KSOPS Secrets in `cluster/apps/litellm/` and `cluster/apps/data/litellm-db.enc.yaml` by `.github/scripts/litellm-k3s-secrets.py` |
| Backups | restic on dgx-1: `pg_dump` from the CNPG primary before each run (`/var/backups/homelab/litellm-db.sql.gz`) |
| AIBOM | the nightly scan on dgx-1 still names the stopped Docker container `litellm-proxy` and `/opt/homelab/litellm` |
| Tailscale | nothing listens on the tailnet. `policies/tailscale/policy.hujson` still grants `tag:agent` and `tag:home` dgx-1:4000 (now unused; removing it is a pending cleanup for you) |
| Docker copy | `hosts/stacks/litellm` (`playbooks/litellm.yml`, which refuses to run without `-e litellm_docker_rollback=true`): stopped with its data as of the cutover, the rollback until 2026-11-23 |
| Runbook | [`runbooks/litellm.md`](https://github.com/nikghodki/homelab/blob/main/runbooks/litellm.md): keys, rotation, guardrail, Phoenix, restore, the move, rollback |

## The move from Docker (2026-11-16)

The relays first (#142), then the app inert (#145; rehearsed on a restored copy with two test pods), then the cutover
at 14:40: the Docker proxy stopped, DGXMM's `litellm_url` switched, `pg_dump` and `pg_restore --single-transaction`
into CNPG, both pods Ready at **+29.9 s**. A ~2 Hz probe through the door answered 615 of 615 requests, **none
failed**; the one in flight at the switch was held by Caddy for 33.7 s. Then Open WebUI was pointed at the ClusterIP,
and the usage exporter and backups moved to CNPG (#153). Rollback until 2026-11-23: runbook, "Rollback".

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

`cluster/apps/litellm/proxy/defenseclaw_guardrail.py`, a global pre-call and pre-MCP-call guardrail (per-key guardrails are
a LiteLLM enterprise feature). Every chat prompt and every MCP tool call goes to dgx-1's DefenseClaw gateway
(`POST /api/v1/agent-gateway/hook`, `connectors.agent_gateway.enabled`, action mode). `block` → HTTP 400 with the
reason. A prompt without an answer runs (fail open, logged); an MCP tool call without one is refused (fail closed).
The judge and scanner keys are skipped (their prompts quote what they judge). DefenseClaw listens on loopback only;
the pods reach it through the relay `litellm-defenseclaw-cable` on dgx-1's direct-cable address `10.100.136.1:18970`
(the Docker copy used one on docker0). If dgx-1 is down, prompts run unchecked (fail open, logged).

## Traces (P2.6, on since 2026-11-15)

LiteLLM's `arize_phoenix` callback sends a trace per request to Phoenix on dgx-2 (`http://192.168.86.36:6006`,
project `litellm`, system API key `litellm-dgx-1`): model, key alias, token counts, prompt and reply.

## Who called the model API

- **Grafana → Fleet → Model API callers** (`/d/model-api-callers/model-api-callers`): calls and errors per key
  alias, latency per model, top callers (24 h), calls per key and source host, and the front door's log per key
  hash. Fed by `litellm-usage-exporter` on dgx-1, which reads the spend log as the read-only role `litellm_usage_ro`
  (a few columns of two tables, read-only transactions) from the CNPG primary (`10.43.0.151:5432`) and publishes metrics with only the first 8 hex
  digits of key hashes (runbooks/litellm.md).
- **Spend logs** on the admin UI's Logs page: key alias and hash, user, team, model, tokens, status, client IP; no
  prompts; kept 30 days (LiteLLM's own cleanup).
- **Phoenix**, project `litellm`, by key alias (with prompts and replies).
- **The front door's access log** in Loki (`service=edge-caddy`).

The client IP is the front door's `X-Forwarded-For`; while the LAN Service uses `externalTrafficPolicy: Cluster` it is
a pod-network address (`10.42.x.x`); callers that don't come through the door (in-cluster, DGXMM, the relays) are
logged with their pod or node address, or whatever `X-Forwarded-For` they send. Trust the key alias.

## Gotchas

- Open WebUI keeps its LiteLLM URL in its database, not its env (`runbooks/open-webui.md`, "Model connection").
- Docker containers on a pod's node (DGXMM) reach the pods with their bridge address (`172.16.0.0/12`), which the
  NetworkPolicy allows explicitly.
- `litellm-admin.nghodki.ai` goes through the front door, which family and guests may reach over Tailscale. Since
  2026-11-16 the door signs you in first (edge-auth, `admins`); the LiteLLM UI login follows.
- Redis stays 7.4 (RSALv2/SSPL, free for private use); the Valkey switch was declined.
