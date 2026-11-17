---
title: "Use the home models in Claude Code, Cursor and Codex"
description: "Point Claude Code, OpenAI Codex CLI and Cursor on a Mac at the homelab LiteLLM (https://model.nghodki.ai): the one-line installer, manual steps per tool, keys in the Keychain, the web CA, and how new DGXMM models reach each tool's model picker."
---

Every model DGXMM serves is a LiteLLM route with the same name (`qwen3.8-27b`, `flint-nvfp4`, …), reachable on the
tailnet at **`https://model.nghodki.ai`**: OpenAI `/v1/chat/completions`, `/v1/responses`, `/v1/models`, and Anthropic
`/v1/messages`. This page connects the coding tools on a Mac to it. The installer does all of it; the manual steps
below say what it does, one tool at a time.

## What works, and how new models show up

| Tool | Talks to LiteLLM | Its model picker | A model newly deployed in DGXMM appears |
|---|---|---|---|
| **Claude Code** (terminal, and the extension in Cursor or VS Code) | `/v1/messages`, key from the Keychain (`apiKeyHelper`) | **synced**: the `/model` rows are written into `~/.claude/settings.json` (`modelPicker`) by the sync agent | within **5 minutes** (the agent's interval), next time you open `/model` |
| **Codex CLI** (and the Codex extension in Cursor) | `/v1/responses`, key from the Keychain (provider `auth` command) | **native**: Codex reads LiteLLM's `/v1/models?client_version=…`, which LiteLLM answers in Codex's catalog format | at the **next start** of `codex` once its catalog cache (`~/.codex/models_cache.json`, 5 minutes) is stale |
| **Cursor's own chat, agent and Tab** | **not possible on the tailnet**: Cursor sends custom-endpoint requests from Cursor's servers, which can't reach `model.nghodki.ai` | — | — |

So no tool needs a manual change when a model is deployed. Why not native discovery for Claude Code too: Claude Code
can read a gateway's `/v1/models` (`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`), but it keeps only IDs that
contain `claude` or `anthropic`, and none of DGXMM's do. Its `modelPicker` setting takes any ID, so the sync agent
writes the list there.

The list holds the chat models the key may use: LiteLLM's `/v1/models`, minus routes whose `/v1/model/info` mode
isn't chat (embeddings, audio, images, rerank) and wildcard routes. An on-demand model that is asleep is listed too;
the first request wakes it (about **4.5 minutes** for `qwen3.8-27b`, longer if memory has to be freed first, and a
model that can't fit next to the running one waits in DGXMM's queue). The default everywhere is `qwen3.8-27b`
(decision 0012).

## Before you start

- **Tailscale** connected on the Mac, with "Use Tailscale DNS" on: `nghodki.ai` only resolves on the tailnet.
- **One LiteLLM key per tool.** Create them at **https://litellm-admin.nghodki.ai** (Pocket ID sign-in) →
  Virtual Keys → **+ Create New Key**, with the key alias:

    | Key alias | Used by |
    |---|---|
    | `claude-code` | Claude Code in the terminal and its extension in Cursor/VS Code (exists already) |
    | `codex` | Codex CLI and the Codex extension |
    | `cursor` | reserved for Cursor's own models, if LiteLLM is ever reachable from outside (see [Cursor](#cursor)) |

    Leave "Models" empty (all models), so new DGXMM models are usable without editing the key. A separate key per
    tool shows up separately in Grafana's "Model API callers" and Phoenix, and can be revoked on its own.
- **macOS 15 or later** (the installer uses the built-in `/usr/bin/jq`).

## The installer

`tools/dev-setup/install-mac.sh` in the homelab repo. Run it in **Terminal on the Mac** (not over SSH: the Keychain is
locked to SSH sessions). Download it, check it, run it:

```bash
curl -fsSLo install-mac.sh https://raw.githubusercontent.com/nikghodki/homelab/dev-setup-v1/tools/dev-setup/install-mac.sh
shasum -a 256 install-mac.sh
# must print: b63702e275ed8df03bb3c0acc9efdbe3ced20b26412b29cb2d784f722ae6aa8a  install-mac.sh
bash install-mac.sh
```

Or in one line, if you trust the tag (it still checks the CA fingerprint it downloads):

```bash
curl -fsSL https://raw.githubusercontent.com/nikghodki/homelab/dev-setup-v1/tools/dev-setup/install-mac.sh | bash
```

**The trade-off.** `curl | bash` runs whatever the URL serves at that moment, before anyone looks at it. The repo
is public and `dev-setup-v1` is a tag: whoever can push tags to `nikghodki/homelab` can move it. Downloading first
and comparing the SHA-256 with this page (served from the private docs site, behind Pocket ID) means a moved tag or
a tampered download is caught before anything runs. Under `curl | bash` the script also can't copy itself for the
sync agent: run it once more from a file to install the agent.

| Option | Does |
|---|---|
| (none) | sets up every tool that's installed: Claude Code (`claude` or `~/.claude`), Cursor (the app), Codex (the CLI or app) |
| `--claude`, `--cursor`, `--codex` | only these tools |
| `--check` | reports, changes nothing; exit code 1 if something needs fixing |
| `--repair` | like a normal run, and also replaces another `apiKeyHelper` or `/model` picker without asking |
| `--uninstall` | removes everything it added (asks before deleting Keychain items) |
| `--yes` | answers yes to its questions (not to macOS's own password dialogs) |
| `--base-url URL`, `--default-model NAME` | defaults `https://model.nghodki.ai`, `qwen3.8-27b` |

Run it again any time: it is idempotent, and it is the repair tool. What it checks and fixes, in order:

1. **`/etc/hosts` pins** for `*.nghodki.ai` (a stale line once sent `model.nghodki.ai` to the retired Jetson front
   door). It shows them, explains, and asks; commenting them out needs `sudo` (your Mac password), and a copy is kept
   as `/etc/hosts.homelab-backup-<time>`.
2. **The endpoint**: the name resolves (Tailscale), `/health/liveliness` answers. `http://` base URLs are flagged.
3. **The web CA** ([PKI](../security/pki.md)): downloaded from the repo (or `ca.nghodki.ai`), **checked against the
   SHA-256 fingerprint pinned in the script** (`D0:5A:E2:93:…:7F:32:C5`, the one of
   `hosts/files/web-ca/nghodki-web-ca.crt`), saved to `~/.config/homelab-models/`. If macOS doesn't trust it yet, the
   script adds it to your login keychain as trusted for SSL (`security add-trusted-cert`): **macOS shows a dialog
   asking for your login password**; that's expected.
4. **Keys**: each tool's key in the Keychain (service `homelab-litellm`, accounts `claude-code`, `codex`), tested
   against `/v1/models`; the key alias is shown. A working key in old `~/.zshrc` exports is moved into the Keychain;
   otherwise it asks (hidden input; Enter reuses the `claude-code` key for Codex).
5. **The Keychain helper** `~/.local/bin/homelab-model-key <account>`: one `security find-generic-password` call.
6. **Your shell**: a marked block at the end of `~/.zshrc` (`# >>> homelab models >>>` … `# <<< homelab models <<<`)
   that sources `~/.config/homelab-models/env.sh`. Old hand-written `export ANTHROPIC_…=` lines are removed (only
   once the key is safely in the Keychain); nothing else in the file is touched.
7. Each tool's config (below), then the **sync agent**, then a **health check**: the model list, a one-line chat
   through LiteLLM, `claude -p` and `codex exec` with the default model (allow 5 minutes if the model is asleep).

Every file it changes is copied first to `~/.local/share/homelab-models/backups/<time>/` (kept 30 days; the first
backup is kept for good); files are replaced atomically (written next to the original, then renamed).

### The sync agent

A user LaunchAgent (`~/Library/LaunchAgents/ai.nghodki.homelab-models.plist`, no sudo) runs
`~/.local/share/homelab-models/install-mac.sh --sync` at login and every 5 minutes. It reads the model list with a
tool key from the Keychain and then, only where something changed:

- rewrites the `/model` rows in `~/.claude/settings.json` (only the `modelPicker` key, and only while the rows are
  its own; every other key in the file stays as it is);
- swaps a model name that LiteLLM no longer serves for the default, in `env.sh`, in the Claude Code extension's
  settings in Cursor, and in Codex's `model`;
- changes nothing when LiteLLM is unreachable or lists no chat models (it keeps the last list).

None of these files has to wait for a tool to quit: Claude Code re-reads its settings when they change (at the latest at
its next start), Cursor reloads its `settings.json` by itself, and Codex reads `config.toml` when it starts. The agent
never edits Cursor's internal database. Log:
`~/Library/Logs/homelab-models.log`. Run it now: `launchctl kickstart -k gui/$(id -u)/ai.nghodki.homelab-models`.

## Claude Code by hand

1. Store the key: `security add-generic-password -U -s homelab-litellm -a claude-code -w` (it prompts for the key).
2. Save the CA: `curl -fsSo ~/.config/homelab-models/web-ca.crt https://raw.githubusercontent.com/nikghodki/homelab/main/hosts/files/web-ca/nghodki-web-ca.crt`
   and check `openssl x509 -in ~/.config/homelab-models/web-ca.crt -noout -fingerprint -sha256`.
3. In `~/.zshrc`:

    ```bash
    export ANTHROPIC_BASE_URL=https://model.nghodki.ai
    export NODE_EXTRA_CA_CERTS=$HOME/.config/homelab-models/web-ca.crt
    export ANTHROPIC_DEFAULT_OPUS_MODEL=qwen3.8-27b ANTHROPIC_DEFAULT_SONNET_MODEL=qwen3.8-27b ANTHROPIC_DEFAULT_HAIKU_MODEL=qwen3.8-27b
    ```

    No `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`: either would win over the helper.
4. In `~/.claude/settings.json`, next to whatever is there:

    ```json
    {
      "apiKeyHelper": "/Users/<you>/.local/bin/homelab-model-key claude-code",
      "modelPicker": {
        "replaceBuiltInOptions": true,
        "options": [{"model": "qwen3.8-27b"}, {"model": "flint-nvfp4"}, {"model": "qwen3-coder-30b-a3b-instruct-fp4"}]
      }
    }
    ```

    `replaceBuiltInOptions` hides the Opus/Sonnet/Haiku rows, which would only be the same models under Anthropic
    names. Without the sync agent, add new models to `options` yourself.
5. Check: `claude -p "say hi"`, then `claude` and `/model`.

Claude Code warns that `qwen3.8-27b` "isn't described by this version's model catalog" and assumes a 200k-token
window; that is expected for a non-Claude model. The extension in Cursor or VS Code runs the same CLI, so it reads
the same `apiKeyHelper` and `modelPicker`; its own environment (`claudeCode.environmentVariables` in the editor's
`settings.json`) needs `ANTHROPIC_BASE_URL` and `NODE_EXTRA_CA_CERTS` as above, and no key. An extension set up for
Bedrock (`CLAUDE_CODE_USE_BEDROCK`) is left alone by the installer.

## Codex by hand

Install Codex (`npm i -g @openai/codex` or `brew install codex`), store its key
(`security add-generic-password -U -s homelab-litellm -a codex -w`), then in `~/.codex/config.toml`, top-level keys
first:

```toml
model = "qwen3.8-27b"
model_provider = "homelab"

[model_providers.homelab]
name = "Homelab LiteLLM"
base_url = "https://model.nghodki.ai/v1"
wire_api = "responses"

[model_providers.homelab.auth]
command = "/Users/<you>/.local/bin/homelab-model-key"
args = ["codex"]
```

and in `~/.zshrc` `export CODEX_CA_CERTIFICATE=$HOME/.config/homelab-models/ca-bundle.pem`: a PEM bundle of the
macOS roots plus the web CA (`security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain`
followed by the CA). Codex is Rust, so `NODE_EXTRA_CA_CERTS` doesn't apply; `CODEX_CA_CERTIFICATE` names a whole CA
bundle, hence the macOS roots in it too. Check: `codex exec --skip-git-repo-check "say hi"`, then `codex` and `/model`: the
LiteLLM models are listed after OpenAI's own. `wire_api = "chat"` no longer exists in Codex; LiteLLM bridges
`/v1/responses` to the models' chat API.

## Cursor

**Cursor's own models can't use LiteLLM here.** With "Override OpenAI Base URL", Cursor still sends every request
from its own servers ("all requests are routed through Cursor's servers for final prompt building"), so a URL that
only resolves on the tailnet and is signed by a private CA can't work. Cursor also has no model discovery (custom
models are added by hand under Settings → Models), and its settings live in an internal SQLite database, not in a
file a script should edit.

What does work inside Cursor, and what the installer sets up with `--cursor`:

- **The Claude Code extension**: the installer points its `claudeCode.environmentVariables` (in
  `~/Library/Application Support/Cursor/User/settings.json`) at `https://model.nghodki.ai` with the CA, fixes model
  names that are gone, and **removes the key from that file**: the extension's CLI then reads it from the Keychain
  through `apiKeyHelper`. Cursor reloads `settings.json` by itself. Its `/model` shows the same synced list.
- **The Codex extension** reads `~/.codex/config.toml`, so `--codex` covers its provider and models. Started from
  the Dock, Cursor doesn't get `CODEX_CA_CERTIFICATE` from `~/.zshrc`, so the extension relies on the CA being
  trusted in the Keychain (step 3) (unverified: Codex isn't installed on the MacBook Air).

Using Cursor's own chat would need LiteLLM reachable from the internet (for example Tailscale Funnel on a dedicated
hostname with a public certificate and its own key, `cursor`), which this setup deliberately doesn't do.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid API key · Fix external API key` from `claude` | no `ANTHROPIC_BASE_URL`: Claude Code went to Anthropic with a LiteLLM key | `install-mac.sh --check`; open a new terminal (the block in `~/.zshrc`) |
| `security: … User interaction is not allowed` (-25308) | run over SSH: the login keychain is locked to SSH sessions | run in Terminal on the Mac; from SSH: `osascript -e 'tell application "Terminal" to do script "…"'` |
| `unable to get local issuer certificate`, `self-signed certificate in chain` | the CA isn't given to that tool | `install-mac.sh --repair`; check `NODE_EXTRA_CA_CERTS` / `CODEX_CA_CERTIFICATE` in a new shell |
| `model.nghodki.ai` resolves to an odd address, or works only over http | a stale `/etc/hosts` line, or Tailscale DNS off | `install-mac.sh` (step 1), `dscacheutil -q host -a name model.nghodki.ai` |
| first answer takes minutes, or times out | the on-demand model is waking (about 4.5 min), or waiting for memory | wait; DGXMM's UI (`dgxmanager.nghodki.ai`) shows the deployment's state |
| 401 from LiteLLM | key revoked or mistyped | new key in the admin UI, then `install-mac.sh --repair` |
| a model missing in `/model` | the sync agent hasn't run, or the key isn't allowed that model | `launchctl kickstart -k gui/$(id -u)/ai.nghodki.homelab-models`; `tail ~/Library/Logs/homelab-models.log` |
| PDF attachments fail | fixed in LiteLLM's request hook (document blocks become text, PR #106) | — |

Operations (tests, updating the installer and its tag, the Gatus check, the keys): `runbooks/dev-tools.md`.

## Sources

Checked 2026-11-16 against Claude Code 2.1.274–2.1.325, Codex CLI 0.169.0, Cursor 3.22 and LiteLLM 1.109.1:

- Claude Code gateway model discovery (the `claude`/`anthropic` filter): https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery
- `modelPicker`, `availableModels`, `apiKeyHelper`: https://code.claude.com/docs/en/settings-reference and https://code.claude.com/docs/en/llm-gateway-connect
- Model aliases and `ANTHROPIC_DEFAULT_*_MODEL`: https://code.claude.com/docs/en/model-config; CA certificates: https://code.claude.com/docs/en/network-config
- Codex providers, `auth` command, `wire_api`: https://learn.chatgpt.com/docs/config-file/config-reference; `CODEX_CA_CERTIFICATE`: https://learn.chatgpt.com/docs/config-file/environment-variables; gateway model catalog: https://learn.chatgpt.com/docs/enterprise/connect-to-a-gateway
- Cursor custom keys go through Cursor's servers: https://cursor.com/help/models-and-usage/api-keys and https://forum.cursor.com/t/connecting-local-ai-server-to-cursor-does-not-work/152940
- LiteLLM Responses API bridge: https://docs.litellm.ai/docs/response_api
- Tested here: Codex 0.169.0 lists LiteLLM's models through the provider `auth` command and refreshes its cache after 5 minutes; `codex exec` answers through `/v1/responses`; Claude Code 2.1.274 and the Cursor extension's 2.1.325 answer through `apiKeyHelper` with no key in the environment.
