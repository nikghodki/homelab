# 0015: DefenseClaw's LLM rescan runs once a week (Sunday 02:00), not every 30 minutes

- Date: 2026-11-17
- Status: decided (nikghodki: "slow only the rescan" — keep `ai_discovery` at 5 min; "timer only" — the gateway's autonomous watch re-scan is off)

## Context

Tracing the fleet's model API calls on 2026-11-17, `defenseclaw-jetson-judge` was by far the heaviest
`qwen3.8-27b` caller: ~2,000 requests/24 h from the Jetson, one every ~15–45 s, in every hour of the day including
3–5 a.m. The source is DefenseClaw's `watch` rescan: with `rescan_interval_min: 30` the gateway re-scans every
skill, plugin and MCP server with the LLM analyzer every 30 minutes, around the clock, on every per-user install
(the Jetson has two, plus the same policy on dgx-1). A full Jetson pass is ~55 plugins × 12–57 s of LLM time
(`~/.defenseclaw/audit.db` `scan_results`), and the model is on demand, so the pass keeps a ~30-min rhythm and a
constant model load.

## Decision

- The **`watch` periodic LLM rescan is off** fleet-wide: `policies/defenseclaw/homelab.yaml` sets
  `rescan_enabled: false` (interval kept at `10080` min as the documented cadence). The policy is the authoritative
  source — `defenseclaw policy activate homelab` overwrites `watch.rescan_interval_min` in the account's
  `~/.defenseclaw/config.yaml`, so a `config set` alone would silently revert on the next playbook run.
- The rescan now runs as a **fixed weekly job**: a systemd **user timer per DefenseClaw account**
  (`homelab-rescan.timer`, role `defenseclaw_rescan`, `OnCalendar=Sun *-*-* 02:00:00` + 10 min random delay,
  `Persistent=true`) that runs the same scan pass standalone — `skill scan --all --use-llm`,
  `plugin scan --all --use-llm`, `mcp scan --all` — and logs one JSON summary line (journal tag `homelab-rescan`
  → Loki). "Every Sunday at 2am PST" cannot be expressed by a 7-day *interval* (it only counts down from the last
  scan), which is why it is a timer.
- **Enabled on**: the Jetson (`nikjetson`, `hermes-nikhil`) and dgx-1 (login user `nikghodki-dgx`) — the accounts
  with per-user 1.0.9 installs and an LLM judge key. The Pi edge connector is out of scope (strict edge build, no
  LLM judge, not a model caller).
- **`ai_discovery` stays at 5 min** (continuous discovery of *new* AI components is unchanged, and the upstream
  `DefenseClawAIDiscoveryStalled` alert — which fires when no discovery scan completes in 30 min and is CI-locked
  to the DefenseClaw release — stays accurate instead of firing daily).
- The timer reproduces the watch's scope **exactly**, not wider: no `--allow-private` on the MCP scan, because the
  watch's own `mcp-scanner` refuses loopback/private URLs by default (the Jetson's `homeassistant` MCP records a
  refusal with exit 1 on every pass — a known normal state the job preserves).

## Alternatives considered

- **Both `ai_discovery` and `watch` to 7 days** (the literal reading of the request): rejected — new AI components
  would be re-discovered only weekly, and the CI-locked upstream `DefenseClawAIDiscoveryStalled` alert would fire
  every day; the rescan is where all the load was.
- **Keep the 7-day watcher *and* the Sunday timer**: rejected — two weekly LLM passes, one at a drifting time.
  The timer alone gives the fixed cadence, so the gateway's autonomous re-scan is off.
- **Leave `watch` at 30 min and only slow the key's rate limit**: rejected — 429s make the scanners fail closed
  (quarantine what they scan); the load is the scan cadence, not a limit to hit.
- **Disable `ai_discovery` entirely** and let the timer do discovery too: rejected (largest security-posture
  change); discovery stays continuous.

## Consequences

- The fleet's continuous `qwen3.8-27b` load drops from ~87 req/hour (Jetson judge key) to ~0 between Sundays, and
  to one burst of a few dozen requests per account per Sunday ~02:00. The model is on demand, so a cold pass after
  the first Sunday may take longer (the pass is capped at 6 h per category by the job and 6 h by the unit).
- A *modified* existing skill/plugin/MCP is LLM-re-checked at most weekly instead of every 30 min. Unchanged:
  scans on install, `ai_discovery` (5 min), the guardrail judge on every call, the nightly AIBOM and MCP drift
  check.
- The policy test (`policies/defenseclaw/tests`) does not pin `watch`, so the cadence change is not guarded; the
  role's job has unit tests (`hosts/roles/defenseclaw_rescan/files/tests`).
- Roll back: restore `watch` in `policies/defenseclaw/homelab.yaml` and rerun `playbooks/defenseclaw.yml` (the
  gateway's 30-min loop resumes); `systemctl --user disable --now homelab-rescan.timer` per account drops the
  timer. Details in runbooks/defenseclaw-rescan.md.
