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
- **Robot motion goes through the Pi's safety governor** (since 2026-11-15, role `hermes_robot_mcp`, playbook
  `robot.yml`; runbooks/robot-safety.md, "Hermes (Jetson)"). `picoclaw-hardware-mcp.js` is patched: its motion tools
  (`drive`, `turn`, `explore`, `go_to_room`, `follow_nearest`, `map_room`) send a structured request to picoclaw over
  MQTT/NATS instead of calling the car, `stop` latches the governor's e-stop over NATS (`robot.pi.safety.estop`; a human
  clears it with `safety-reset`) and calls the car's `/stop`, and Nav2/follow-me are disabled. The file has no direct
  `/drive`, `/turn` or `/velocity` call (checked by the role and by the nightly drift check). The original is
  `picoclaw-hardware-mcp.js.pre-governor`. The role restarts this profile's `hermes-gateway` when it changes the file;
  after the change Hermes logged `picoclaw_only` with 2 tools and no MCP errors.
- WhatsApp was never paired for this profile.
- DefenseClaw can't scan its MCP servers (local/private by design; a path launcher isn't allowlisted). They're kept
  with a warning, the same as on the main gateway; admission and the nightly drift check are in
  [mcp-admission.md](mcp-admission.md).

## MCP servers

| Profile | MCP servers |
|---|---|
| main (`nikjetson`) | `homeassistant` |
| nikhil-ghodki (`hermes-nikhil`) | `homeassistant`, `picoclaw_only` (tools include-list: `send_to_picoclaw_agent`, `check_picoclaw_agent_connection`; the server's motion tools go through picoclaw and the governor either way) |

Only servers in `policies/defenseclaw/mcp-servers.yaml` are approved (runbooks/mcp-admission.md).

Removed 2026-11-15 (they failed at every start): `wedding` (both profiles; `~/workspace/nandita-wedding` no longer
exists and `/usr/bin/node` is gone since the JP7 reflash), `home-board` (hermes-nikhil; the Home Board is
decommissioned, 100.65.137.82:8400 does not answer) and `vision-ai` (hermes-nikhil; vision is skipped by decision).
Removed by deleting only their blocks under `mcp_servers:` (line-based, every other line of `config.yaml` kept, checked
by parsing before and after); backups in `~/.hermes/backups/config/config.yaml.pre-mcp-cleanup.20261115-172246` of each
account. After restarting both `hermes-gateway` units the logs show `homeassistant` (28 tools: 24 from the server plus
Hermes' own resource/prompt helpers) on both and `picoclaw_only` (2 tools) on hermes-nikhil, with no MCP errors.

Left as they were, for the profile owner to clean up: hermes-nikhil's `skills/smart-home/home-board` skill and the
first line of its `memories/MEMORY.md` (groceries on the Home Board) still describe the decommissioned board, and old
`config.yaml.bak*` copies still list the removed servers.

## Skill scanner and LLM judge (back on since 2026-11-16)

- Both accounts: `defenseclaw setup skill-scanner --use-llm --non-interactive`, and `guardrail.judge.enabled: true`.
  The unified `llm:` block is `openai` / `qwen3.8-27b` / `http://model.nghodki.ai/v1` with `DEFENSECLAW_LLM_KEY` = the
  LiteLLM key `defenseclaw-jetson-judge` (decision 0012; nikjetson's old `defenseclaw-jetson` key is no longer used).
  `defenseclaw setup llm --non-interactive ...` with the key in `DEFENSECLAW_SETUP_LLM_API_KEY` (not on argv), then
  `defenseclaw-gateway restart`: the running gateway keeps the old key in its environment until it restarts.
- Timeouts raised for a model that thinks: `scanners.skill_scanner.llm.timeout 900`,
  `scanners.skill_scanner.timeouts.scan_s 1800`, `scanners.plugin_llm.timeout 900`, `scanners.mcp_scanner.llm.timeout 900`.
  DefenseClaw 1.0.9's plugin watcher still kills its LLM call after a fixed 120 s, so the judge key is mapped in
  LiteLLM to `qwen3.8-27b-nothink` (thinking off; runbooks/litellm.md). With thinking on, a plugin analysis took
  2–5 minutes under load and every one of them failed closed again.
- The judge key allows 6 requests in flight: at 2–4 the scanners hit 429s, and after 4 retries they fail closed
  ("the LLM judge did not run"), which quarantines what they scan.
- Changing scanner settings makes the gateway rescan every skill (`scanner-fingerprint-changed`), about an hour per
  account. During it a failed scan doesn't overwrite the baseline (F-3188), so nothing new is quarantined.

### What the LLM rescan changed (2026-11-16)

A rescan doesn't release a quarantine: the files are in `~/.defenseclaw/quarantine/`. Each active quarantine was
scanned again in place with the LLM analyzer (`defenseclaw skill scan --path <quarantine copy> --json`,
`defenseclaw plugin scan <quarantine copy> --use-llm --json`) and restored only if nothing was HIGH or above and the
LLM had run (`skill restore` + `skill unblock`; DefenseClaw can't restore category plugins by name, so those were
copied back with `cp -a`, after which the watcher scanned them again and admitted or re-quarantined them). Nothing
was allow-listed. Scripts: `/tmp/skill_rescan.py`, `/tmp/plugin_rescan.py` on the Jetson; logs
`/tmp/{skill,plugin}-rescan-<user>.log`.

**Hermes plugins.** On 2026-11-15 (09:20–12:20 UTC), while the model was down, the plugin watcher had quarantined
every Hermes plugin it rescanned ("scanner failure: the LLM judge did not run"), including `plugins/browser/*`, which
Hermes imports for every chat: the API server answered `500 No module named 'plugins.browser.browser_use'` (Slack and
the API were broken). After the rescan:

| | nikjetson | hermes-nikhil |
|---|---|---|
| Restored (clean or MEDIUM at most, LLM ran) | 47 | 81 |
| Still quarantined, HIGH or CRITICAL with the LLM | a2a, buzz, discord, google_meet, homeassistant (`~/.hermes/plugins`), irc, kanban/dashboard, memory/byterover, memory/retaindb, photon, raft, simplex, slack, teams, whatsapp, whatsapp-agent-platform | a2a, email, kanban/dashboard, ntfy, observability/langfuse, raft, simplex |

Hermes chat works again on both profiles (API server, 2026-11-16).

**Skills.** The ones the static scan had quarantined for "scanner failure" (ascii-video, pretext, design-md,
huggingface-hub, serving-llms-vllm, audiocraft-audio-generation, segment-anything-model, teams-meeting-pipeline,
blogwatcher, jupyter-live-kernel, architecture-diagram, home-assistant) are back at their paths and scan clean or
with warnings; their old quarantine records stay listed. The ones blocked for findings stay blocked; the LLM
confirmed the findings:

| Skill | Account(s) | Still blocked because (HIGH/CRITICAL rules, static + LLM) |
|---|---|---|
| roboclaw | nikjetson | CORRELATED_NETWORK_EXECUTION_FLOW |
| github-code-review, github-repo-management, github | nikjetson | PATH-ENV-FILE, PATH-GIT-CREDS, PATH-SSH-DIR, PATH-SSH-KEY |
| github-workflow | hermes-nikhil | PATH-GIT-CREDS |
| ocr-and-documents | nikjetson | PATH_TRAVERSAL_OPEN |
| pdf | hermes-nikhil | PATH_TRAVERSAL_OPEN |
| godmode | both | ACTIVE_DYNAMIC_EXECUTION, COMMAND_INJECTION_EVAL, LLM_COMMAND_INJECTION, LLM_PROMPT_INJECTION, PATH-ENV-FILE |
| touchdesigner-mcp | both | COMPOUND_FETCH_EXECUTE |
| evaluating-llms-harness | both | ACTIVE_DYNAMIC_EXECUTION |
| google-workspace | nikjetson | ACTIVE_REMOTE_ACQUIRE_EXECUTE, CORRELATED_NETWORK_EXECUTION_FLOW |
| xurl | nikjetson | CORRELATED_NETWORK_EXECUTION_FLOW, LLM_SUPPLY_CHAIN_ATTACK |
| notion, himalaya | nikjetson | CORRELATED_NETWORK_EXECUTION_FLOW (himalaya also LLM_COMMAND_INJECTION) |
| comfyui, p5js, hermes-agent | both | scan can't finish: the gateway rejects the audit event ("invalid finding fields; the CLI and the gateway may be different versions"), a DefenseClaw 1.0.9 bug; they stay quarantined |

New on the rescan (nikjetson): `obliteratus` went from clean to rejected (HIGH); 16 skills went from clean to
warning (INFO findings from the LLM).

## Rollback

nikjetson's old `hermes-gateway-nikhil-ghodki` unit is disabled but kept, and its data is still in
`~/hermes-homes/nikhil-ghodki`. To roll back: stop `hermes-gateway` as hermes-nikhil, then
`systemctl --user enable --now hermes-gateway-nikhil-ghodki` as nikjetson. Delete the old copy once the new one has
been used for a while.
