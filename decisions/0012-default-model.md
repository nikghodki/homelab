# 0012: Default model = qwen3.8-27b for all fleet LLM consumers

- Date: 2026-11-15
- Status: decided (by nikghodki)

## Context

With the LiteLLM security window (P0.14, P2.4, P2.6, P1.11) the LLM-backed checks came back on: DefenseClaw's
judge and skill scanner on the Jetson and dgx-1, Cisco AIBOM's agentic stage, plus the agents (Hermes, picoclaw)
and Open WebUI. Each had its own model setting, some empty, some pointing at models that no longer exist. The model
aliases of the architecture (`smart`, `guard`, …, plan P2.0) are not decided yet. DGXMM serves five on-demand models
through LiteLLM; `qwen3.8-27b` is the general-purpose one every agent already used.

## Decision

Every fleet LLM consumer uses `qwen3.8-27b` through LiteLLM (`http://model.nghodki.ai/v1`, or
`http://127.0.0.1:4000/v1` on dgx-1). Dedicated keys for judges and scanners are scoped to `qwen3.8-27b` only, with
rate limits (runbooks/litellm.md).

> Note (2026-11-16): LiteLLM moved into k3s. `127.0.0.1:4000` on dgx-1 is now only a transition relay, removed on
> 2026-11-23; in-cluster callers and DGXMM use the ClusterIP `http://10.43.0.150:4000/v1`, everything else the front
> door (runbooks/litellm.md, "Callers"). The decision itself is unchanged.

Set on 2026-11-15:

| Consumer | Setting | Before → after |
|---|---|---|
| DefenseClaw, Jetson `nikjetson` | `llm:` (judge, skill/MCP/plugin scanners) | `qwen3.8-27b` (key `defenseclaw-jetson`) → `qwen3.8-27b`, key `defenseclaw-jetson-judge` |
| DefenseClaw, Jetson `hermes-nikhil` | `llm:` | empty → `qwen3.8-27b`, key `defenseclaw-jetson-judge` |
| DefenseClaw, dgx-1 | `llm:` | `openai/qwen3.8-27b` (unchanged; the `openai/` prefix is the provider) |
| DefenseClaw judge, all three | `guardrail.judge.enabled` | false → true (inherits `llm:`) |
| skill-scanner, both Jetson users | `scanners.skill_scanner.use_llm` | false → true (inherits `llm:`) |
| Cisco AIBOM, every host | `cisco_aibom_llm_model` (`/etc/cisco-aibom/llm.env`) | none (closed port) → `qwen3.8-27b`, key `cisco-aibom` |
| Hermes, both profiles | `model.default` | already `qwen3.8-27b`; no fallback providers; auxiliary tasks on `auto` (the main model) |
| picoclaw | `agents.defaults.model_name` → `dgx-qwen` → `qwen3.8-27b` | already; key rotated |
| Open WebUI | `ui.default_models`, `task.model.external`, tool-permission and tool-search decision models | none / none / `gpt-6-luna` (doesn't exist) → `qwen3.8-27b` |

CI keeps its scanners offline (no LLM calls are added to CI).

In the same window, the tool review's item 3 (Redis → Valkey for LiteLLM) was declined: Redis 7.4 under
RSALv2/SSPL is free for private use; LiteLLM keeps `redis:7-alpine`, now pinned by digest. Revisit only if licensing
needs change.

## Alternatives considered

- **Wait for the aliases (P2.0).** Rejected: the scanners would stay static-only (stricter, with false-positive
  quarantines) until then.
- **A smaller model for the judges (`twil-8b`).** Rejected for now: a second on-demand model would start next to the
  main one and compete for the Spark's memory; one warm model serves everyone.

## Consequences

- One model to keep warm; its cold start (about 4.5 min) hits whoever calls first after it sleeps.
- The Jetson scanner/judge key gets `qwen3.8-27b` with thinking off (LiteLLM key alias to the route
  `qwen3.8-27b-nothink`, 2026-11-16): DefenseClaw's plugin watcher allows its LLM call only 120 s.
- When the P2.0 aliases exist, only LiteLLM changes (an alias such as `smart` pointing at `qwen3.8-27b`), then the
  consumers move to the alias name.
- The three disabled Hermes cron jobs (nikjetson: the two Saapaadu Haldi lunch reminders and the daily wedding
  status report) named `anthropic`/`claude-sonnet-4`. Set to `qwen3.8-27b`, provider `custom`, on 2026-11-16 with
  `hermes cron edit`; they stay paused (`enabled: false`). Backup: `~/.hermes/cron/jobs.json.bak-20261116-model`.
