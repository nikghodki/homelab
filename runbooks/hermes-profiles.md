# Hermes profiles on the Jetson (plan P0.15)

DefenseClaw's Hermes connector covers one `HERMES_HOME` per account, so each Hermes profile runs as its own Linux
user with its own per-user DefenseClaw.

| Profile | Linux user | Hermes unit (user) | DefenseClaw gateway | Platforms |
|---|---|---|---|---|
| main | `nikjetson` | `hermes-gateway` | 127.0.0.1:18970 | api_server :8642, … |
| nikhil-ghodki | `hermes-nikhil` (linger on) | `hermes-gateway` | 127.0.0.1:18980 (`gateway.port` 18971) | Slack, Home Assistant, api_server 100.78.145.123:8643 |

Both DefenseClaw installs run 1.0.9 in action mode, fail closed, with human approval at MEDIUM, the `homelab` policy
(role `defenseclaw_policy`, `defenseclaw_policy_users` in `host_vars/jetson.yml`), and OTLP to dgx-2 with `sensitive`
redaction.

## hermes-nikhil details

- Hermes runtime: its own checkout of the same commit (`~/.hermes/hermes-agent`, `setup-hermes.sh --runtime-only`), not
  shared with nikjetson.
- MCP `picoclaw_only` runs nikjetson's `~/workspace/roboclaw/mcp-server` through read-only ACLs (`setfacl`: x on the
  parent folders, rX on `mcp-server`); nothing else in nikjetson's home is readable. It uses Hermes' bundled Node
  (`/usr/bin/node` is gone since the JP7 reflash) and NATS as user `hermes` (`~/.picoclaw-nats-credentials`, 0600,
  from `secrets/bus.enc.yaml`).
- MCP servers that still fail, as before the move: `wedding` (folder no longer exists), `home-board` (decommissioned),
  `vision-ai` (vision is skipped). WhatsApp was never paired for this profile.
- DefenseClaw can't scan these MCP servers (local/private by design; a path launcher isn't allowlisted). They're kept
  with a warning, the same as on the main gateway.

## Skill scanner (temporary: LLM judge off)

- Since 2026-11-15 the skill scanner runs static-only for both accounts (`scanners.skill_scanner.use_llm: false`,
  set with `defenseclaw setup skill-scanner --no-use-llm --non-interactive`), because the LLM behind LiteLLM is down
  during the DGXMM work. Static-only is stricter: it can't clear the false positives the judge used to clear.
- **Re-enable it once the model is back**, as each account: `defenseclaw setup skill-scanner --use-llm`, then
  `defenseclaw skill scan all`. Skills that the static scan quarantined (below) may pass again then.
- The gateway needs `~/.local/bin` on PATH (that's where `skill-scanner` and `mcp-scanner` live). Without it the
  scanner fails closed and the policy quarantines every skill it rescans. Role `defenseclaw_gateway_env` writes the
  `defenseclaw-gateway.service.d/10-path.conf` drop-in for each account in `defenseclaw_policy_users`.
- Recovering skills quarantined for "scanner failure": `defenseclaw skill restore <name>` then
  `defenseclaw skill unblock <name>`. DefenseClaw 1.0.9 refuses the restore when the skill's folder name differs from
  its `name:` (for example `mlops/models/segment-anything` vs `segment-anything-model`) or when the copy sits under
  `quarantine/per-source/`; then copy the quarantine folder back to the recorded original path (`cp -a`, the path is
  in `quarantine_records` in `~/.defenseclaw/audit.db`) and rescan. The stale quarantine record stays listed.

## Rollback

nikjetson's old `hermes-gateway-nikhil-ghodki` unit is disabled but kept, and its data is still in
`~/hermes-homes/nikhil-ghodki`. To roll back: stop `hermes-gateway` as hermes-nikhil, then
`systemctl --user enable --now hermes-gateway-nikhil-ghodki` as nikjetson. Delete the old copy once the new one has
been used for a while.
