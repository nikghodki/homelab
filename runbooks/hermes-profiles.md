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

API server keys: `secrets/hermes.enc.yaml` (`hermes_api_key_nikjetson`, `hermes_api_key_hermes_nikhil`), deployed by
hand to each account's `~/.hermes/api_server.env` (0600); both rotated on 2026-11-17. Only Open WebUI calls the main
profile's API (runbooks/open-webui.md, "Hermes": rotation steps, the Jetson-side allow rule).

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

## Restarts and quarantined plugins (2026-11-17)

A gateway restart reloads every plugin from disk, so anything DefenseClaw's watcher quarantined since the last start
disappears from the running agent. The watcher kept quarantining plugins with "the LLM judge did not run" in both
accounts (dozens on 2026-11-16); the cause is [below](#why-the-watcher-kept-quarantining-plugins). After the key
rotation restart on 2026-11-17 (01:00 UTC):

- nikjetson: chats failed with `No module named 'plugins.browser.browser_use'` (then `browserbase`). Rescanned in
  place with the LLM and restored as before (none HIGH+): `browser/browser_use`, `browser/browserbase`,
  `browser/firecrawl`, `web/ddgs`, `web/exa`. `browserbase` was quarantined again by a timed-out watcher scan and
  admitted on the second try.
- hermes-nikhil: `browser/browser_use` and `browser/firecrawl` restored the same way. **Slack is down**: the watcher
  rejected `plugins/platforms/slack` as CRITICAL on 2026-11-16 07:39 UTC (findings about `src/index.ts` and
  `package.json`, files the plugin doesn't have) and again at 01:08 UTC after a clean manual rescan, so the restarted
  gateway has no Slack adapter. The `homeassistant` platform plugin (`~/.hermes/plugins/homeassistant`) rescanned HIGH
  and stays quarantined. Both need a human decision (allow-list or keep off).

## Why the watcher kept quarantining plugins

Found 2026-11-17 (qwen3.8-27b loaded, so not a timeout): the watcher blocked `browser/browser_use` with "scanner
failure (fail-closed): the LLM judge did not run … judge openai/qwen3.8-27b: The LLM analyzer was enabled but returned
JSON that was not the expected array of findings". A manual rescan passed. After the restore the watcher allowed it,
and the rescan after the next restart blocked it again.

- **Cause.** DefenseClaw 1.0.9's plugin analyzer accepts only a bare JSON array. qwen3.8-27b, even with thinking off,
  answers about 8% of plugin judge calls differently. Of 758 calls (2026-11-16 06:16 UTC to 2026-11-17 02:00 UTC),
  62 failed: 49 sent one finding object instead of a one-item array, and the rest were prose, broken JSON or
  `{"error": …}`. Each failure is `LLM-SCAN-ERROR`, which the watcher treats as a failed scan and quarantines (fail
  closed), even for a plugin it admitted minutes before.
- **Fix.** LiteLLM repairs these replies, but only for the judge keys and the plugin analyzer's prompt. It never
  invents findings and leaves doubtful replies unchanged, so DefenseClaw still fails closed (#189;
  [litellm.md](litellm.md#defenseclaw-judge-replies)). Measured on those 758 replies, DefenseClaw reads 98.4%, up
  from 91.8%. Replaying the `browser_use` judge prompt 10 times parsed 10/10 both before and after the change: on
  that prompt the failure is intermittent, so the corpus is the meaningful number. Both judge keys
  (`defenseclaw-jetson-judge`, `defenseclaw-dgx1`) map `qwen3.8-27b` to `qwen3.8-27b-nothink` (no reasoning tokens).
- **Still possible.** The watcher's LLM call has a fixed 120 s limit, so a scan while the model is cold (about 280 s
  to load) still times out and fails closed. The fix also doesn't help when the judge is given no code (next point).
- **The judge can be given no code at all.** DefenseClaw sends at most 50,000 bytes of source and stops at the first
  file that doesn't fit. Slack's `adapter.py` is 372 KB and dingtalk's is 52 KB, so for these plugins the judge gets
  only `## Plugin: <name>\n\n## Source files\n`. It then answers `[]`, or hallucinates: "CRITICAL Credential
  Exfiltration @ src/index.ts:42", "eval @ src/handler.ts", for files these Python plugins don't have. Restoring
  such a plugin doesn't last, because the next rescan can hallucinate again. Upstream draft:
  [docs/upstream-issues/09](../docs/upstream-issues/09-plugin-judge-unparseable-reply-quarantines.md).

### Restore after the fix (2026-11-17, 02:20–03:20 UTC)

Each quarantine copy was rescanned with the LLM by `hosts/files/defenseclaw/plugin_rescan_restore.py` (as the profile
user). A plugin was copied back only if the LLM ran and nothing was HIGH or above, and `git status` of the restored
path was clean every time (the files are the checkout's own). The watcher then scanned each one again. Nothing was
allow-listed.

| | nikjetson | hermes-nikhil |
|---|---|---|
| Scope | every plugin whose files were gone and whose latest block was a scanner failure (59 + a retry) | `browser/browser_use` (already back since 02:08 UTC), `web/firecrawl`, `platforms/slack`; then `browser/browserbase` (quarantined again at 02:09 UTC, before the fix rolled out) |
| Restored and admitted by the watcher (before the restart) | 41: `cron_providers/chronos`, `dashboard_auth/*` (4), `disk-cleanup`, `hermes-achievements/dashboard`, `image_gen/*` (8), `model-providers/*` (9), `platforms/{email,line,matrix,telegram,wecom}`, `video_gen/*` (4), `web/*` (8) | `browser/browser_use`, `browser/browserbase`, `web/firecrawl`, `platforms/slack` |
| Rejected by the watcher's own LLM rescan | `platforms/dingtalk` (CRITICAL, hallucinated: `src/config.ts`, `src/processor.ts`), `platforms/mattermost` (HIGH: `_load_batch_image` reads `file://` URLs, `adapter.py:373`, real) | after the restart, see below |
| Kept: HIGH or CRITICAL on the rescan | `google_meet`, `kanban/dashboard` (`exec()` in `dist/index.js`), `memory/byterover`, `memory/retaindb`, `platforms/{a2a,buzz,discord,irc,ntfy,photon,raft,simplex,sms,teams,whatsapp}`, `~/.hermes/plugins/homeassistant` | — |

Unchanged since before: nikjetson's `platforms/slack` (static HIGH `PATH-ENV-FILE`, besides hallucinated LLM
findings), `computer_use/cua`, `observability/langfuse`, `platforms/{feishu,google_chat}` and
`whatsapp-agent-platform` stay quarantined for findings. The other hermes-nikhil plugins that are still in quarantine
for scanner failures (`image_gen/*`, `model-providers/*`, `web/*`, `video_gen/*`, `dashboard_auth/*`, most
platforms) weren't in scope; `plugin_rescan_restore.py scanner-failures` as hermes-nikhil would do them.

**After the single restart of each gateway (03:20 UTC):**

- 5 minutes later (03:25–03:27 UTC): every restored plugin was still in place in both accounts, except the two the
  watcher had already rejected before the restart (nikjetson `platforms/dingtalk`, `platforms/mattermost`).
  nikjetson logged no import errors. hermes-nikhil logged `No module named 'plugins.browser.browserbase'` at start-up
  (`tools.browser_tool`): browserbase had been quarantined again at 02:09 UTC, before the fix rolled out. It was
  restored at 03:21 UTC and admitted at 03:23 UTC, but the running agent only picks it up at the next restart. Slack
  connected on hermes-nikhil ("Socket Mode connected", "slack connected"). Test chats ("what time is it?", no tools)
  answered 200 on both API servers, and the Pi's governor logged no command.
- The watcher's rescan after the restart (cycle complete 03:32 UTC for hermes-nikhil, 03:34 UTC for nikjetson)
  rejected three of them again:
  - hermes-nikhil `platforms/slack`, CRITICAL: hallucinated (`src/index.ts:42`, `src/index.ts:18`; the judge saw no
    code).
  - hermes-nikhil `web/firecrawl`, HIGH: "Credential leakage in client cache key", `provider.py:186`. This is real
    code, but the same finding was MEDIUM in all three manual rescans and in the watcher's 02:29 UTC scan: the model
    varies on the severity.
  - nikjetson `platforms/email`, CRITICAL: hallucinated (`src/config.ts`, `src/processor.ts`).

  Nothing else was rejected (31 verdicts). The running agents keep what they loaded at 03:20 UTC: Slack stays
  connected and `tools.web_tools` keeps firecrawl until the next restart of hermes-nikhil's gateway. After that
  restart, Slack is gone and `tools.web_tools` breaks again (`No module named 'plugins.web.firecrawl'`), unless a
  human decides first (allow-list or keep them off). End state: nikjetson 40 of the 43 restored plugins in place;
  hermes-nikhil `browser/browser_use` and `browser/browserbase` in place, Slack and firecrawl quarantined.

## After any Hermes restart

1. Wait for the watcher's rescan to finish (`grep '\[rescan\]\|watcher verdict' ~/.defenseclaw/gateway.log`, about 30–60 s
   per plugin), then look for import errors: `grep -i 'no module named' ~/.hermes/logs/agent.log` (the log is in local
   time, PST; DefenseClaw logs in UTC).
2. List what is missing and why: the newest `quarantine_records` row per `original_path` in `~/.defenseclaw/audit.db`
   (read-only), for paths that no longer exist. A scanner failure ("the LLM judge did not run", a timeout, a 429) is
   not a finding.
3. As the profile user, in a login shell, from a copy of `hosts/files/defenseclaw/plugin_rescan_restore.py`:
   `plugin_rescan_restore.py scanner-failures`, or `named <category>/<plugin> …`. It restores only what rescans with
   the LLM and nothing HIGH or above, and never allow-lists anything.
4. Check the watcher's verdict for each restored plugin (platform plugins are logged by bare name, `plugin slack`).
   A plugin that is imported at start-up (`tools.browser_tool` needs `browser/browserbase`) is only picked up by the
   next restart, and a restart triggers the next rescan, so restore everything first and restart once.
5. Plugins the watcher rejects with findings about files the plugin doesn't have (Slack, dingtalk) need a human
   decision: allow-list them, or leave them off until DefenseClaw stops judging empty prompts.

## Rollback

nikjetson's old `hermes-gateway-nikhil-ghodki` unit is disabled but kept, and its data is still in
`~/hermes-homes/nikhil-ghodki`. To roll back: stop `hermes-gateway` as hermes-nikhil, then
`systemctl --user enable --now hermes-gateway-nikhil-ghodki` as nikjetson. Delete the old copy once the new one has
been used for a while.
