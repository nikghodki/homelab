# Coding tools on a Mac → LiteLLM (Claude Code, Codex, Cursor)

How a Mac's Claude Code, Codex CLI and the Claude Code extension in Cursor reach the home models, and how to look
after that setup. User guide (install line, manual steps, troubleshooting):
`docs-site/content/docs/agents/coding-tools.md` (docs site: Agents and AI → Use the home models in Claude Code, Cursor and Codex).

| | |
|---|---|
| Installer | `tools/dev-setup/install-mac.sh` (bash 3.2, BSD tools, `/usr/bin/jq`; macOS 15+). Run by the user on the Mac, in Terminal. Not deployed by Ansible: the Mac stays outside the fleet (D18) |
| Install line | `https://raw.githubusercontent.com/nikghodki/homelab/dev-setup-v1/tools/dev-setup/install-mac.sh`; the page shows its SHA-256 |
| Endpoint | `https://model.nghodki.ai` (front door → LiteLLM). Claude Code: `/v1/messages`; Codex: `/v1/responses` and `/v1/models?client_version=…` (LiteLLM's Codex catalog); the sync agent: `/v1/models`, `/v1/model/info` |
| Keys | login Keychain, service `homelab-litellm`, accounts `claude-code`, `codex` (and `cursor`, reserved); LiteLLM key aliases of the same names, created by the user in the admin UI, all models. Read by `~/.local/bin/homelab-model-key <account>` |
| CA | `hosts/files/web-ca/nghodki-web-ca.crt`, fingerprint pinned in the script (`HL_CA_SHA256`); on the Mac `~/.config/homelab-models/web-ca.crt` (`NODE_EXTRA_CA_CERTS`) and `ca-bundle.pem` (macOS roots + CA, `CODEX_CA_CERTIFICATE`); login-keychain trust for Keychain-based apps |
| Files on the Mac | `~/.config/homelab-models/` (env.sh, CA, state, last model list), `~/.local/share/homelab-models/` (the agent's copy of the script, backups), the block in `~/.zshrc`, `apiKeyHelper` + `modelPicker` + per-model `modelSettings.<model>.autoCompactWindow` (context windows from `/v1/model/info`) in `~/.claude/settings.json`, the `homelab` provider in `~/.codex/config.toml`, `claudeCode.environmentVariables` in Cursor's `settings.json` |
| Sync agent | LaunchAgent `ai.nghodki.homelab-models` (user, every 5 min, `--sync`); log `~/Library/Logs/homelab-models.log` |
| Tests | `bash tools/dev-setup/tests/run.sh` (pure logic on fixtures, LiteLLM stubbed; CI "Unit tests: Mac dev-setup"); shellcheck in CI |
| Monitoring | Gatus `model.nghodki.ai lists qwen3.8-27b` (Dell): `/v1/models` through the front door with key `gatus-models` |

## Check a Mac

In Terminal on the Mac (not SSH: the Keychain is locked to SSH sessions, error -25308):

```bash
bash ~/.local/share/homelab-models/install-mac.sh --check      # exit 1 if anything needs fixing
bash ~/.local/share/homelab-models/install-mac.sh --repair     # fix it
tail ~/Library/Logs/homelab-models.log
```

From another machine over SSH, run it through Terminal: `osascript -e 'tell application "Terminal" to do script
"bash ~/.local/share/homelab-models/install-mac.sh --check > /tmp/hl-check.log 2>&1; exit"'`, then read the log.

## A new model in DGXMM

Nothing to do on the Macs. DGXMM registers the route in LiteLLM; within 5 minutes the sync agent adds it to Claude
Code's `/model`, and Codex lists it at its next start (its catalog cache lasts 5 minutes). A removed model disappears
the same way, and a tool whose default it was falls back to `qwen3.8-27b`. The key must allow the model: the tool
keys are created with all models.

## Rotate a tool's key

Create the new key in the admin UI (same alias), delete the old one, then on the Mac
`security add-generic-password -U -s homelab-litellm -a <account> -w` (prompts) or `install-mac.sh --repair`
(asks when the stored key is refused). Claude Code re-runs `apiKeyHelper` after a 401 or 5 minutes; Codex every 5
minutes.

## Change the installer

1. Edit `tools/dev-setup/install-mac.sh`, run `bash tools/dev-setup/tests/run.sh` and shellcheck, and test on a
   Mac: `--check`, then an install in a temporary `HOME` (`HOME=/tmp/x HL_TEST_KEYDIR=/tmp/x/keys
   HL_NO_LAUNCHCTL=1 bash install-mac.sh --claude --cursor --codex --yes`: keys in files instead of the Keychain,
   no LaunchAgent; test only).
2. Put the new `shasum -a 256` into the page's "must print" line (the tests fail until it matches).
3. After the merge, move the tag to the merge commit and push it (from dgx-1):
   `git tag -f dev-setup-v<n> <commit> && git push origin dev-setup-v<n>`. Prefer a new `v<n>` and update the page
   over moving an existing tag. Macs pick up the new version with the install line, or
   `install-mac.sh --repair` from a downloaded copy (the agent runs its own copy).

## The Gatus check

`hosts/stacks/alerting/gatus/config.yaml.j2`, `model.nghodki.ai lists qwen3.8-27b`: `GET https://192.168.86.11/v1/models`
(Host `model.nghodki.ai`) every 5 min, `[BODY].data[0].id == qwen3.8-27b`. Key `gatus-models`: models
`qwen3.8-27b` only, `allowed_routes` `/v1/models` and `/models` (a chat gets 403), 2 rpm, $0.01 budget; its value is
`gatus_litellm_models_key` in `secrets/observe.enc.yaml` (`playbooks/alerting.yml`). Failing means the default model's
route is gone (DGXMM unregistered it) or LiteLLM or the front door is down; the liveliness check next to it tells which.
Deploy a change: from `hosts/`, `ansible-playbook playbooks/alerting.yml --check --diff`, then without `--check`.

## Cursor's own models

Not connected, by design: Cursor calls a custom OpenAI base URL from its own servers, which can't reach the tailnet
or trust the web CA. Making that work means publishing LiteLLM on the internet (for example Tailscale Funnel on a
separate hostname with a public certificate, a dedicated `cursor` key with a model allowlist and rate limits, and the
DefenseClaw guardrail). That is a decision for the owner, not part of this setup.
