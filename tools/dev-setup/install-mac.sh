#!/usr/bin/env bash
# Connect Claude Code, Codex CLI and Cursor on a Mac to the homelab's LiteLLM (https://model.nghodki.ai).
# Page: docs-site/content/docs/agents/coding-tools.md. Runbook: runbooks/dev-tools.md.
#
#   install-mac.sh [--claude] [--cursor] [--codex] [--check | --repair | --uninstall] [--yes]
#                  [--base-url URL] [--default-model NAME]
#
# Without a tool flag it sets up every tool that is installed. It is idempotent: run it again to repair. Every file it
# changes is copied to ~/.local/share/homelab-models/backups/<time>/ first. API keys live only in the login Keychain
# (service "homelab-litellm", one account per tool); this script never prints them and never writes them to a file.
# The model list is kept in sync by a user LaunchAgent (ai.nghodki.homelab-models) that runs this script with --sync
# every 5 minutes. Needs macOS 15 or later (/usr/bin/jq). Plain bash 3.2 and BSD tools; no sudo except for /etc/hosts.
set -u -o pipefail

HL_VERSION=1
HL_BASE_URL_DEFAULT=https://model.nghodki.ai
HL_DEFAULT_MODEL_DEFAULT=qwen3.8-27b
# SHA-256 fingerprint of the homelab web CA (hosts/files/web-ca/nghodki-web-ca.crt): the download is checked against it
HL_CA_SHA256=D05AE29351C50101CFBCEEC7270EE42B80AAD4DC37EA73B9B6548D5D077F32C5
HL_CA_URLS="https://raw.githubusercontent.com/nikghodki/homelab/main/hosts/files/web-ca/nghodki-web-ca.crt http://ca.nghodki.ai/nghodki-web-ca.crt"
HL_KC_SERVICE=homelab-litellm
HL_LABEL=ai.nghodki.homelab-models
HL_MARK_BEGIN='# >>> homelab models >>>'
HL_MARK_END='# <<< homelab models <<<'
# Written into every row this script adds to Claude Code's /model picker; how the sync agent knows the picker is its own
HL_PICKER_TAG='homelab LiteLLM'
# LiteLLM model_info.mode values that are not chat models (a route without a mode counts as chat)
HL_NON_CHAT_MODES='embedding image_generation image_edit audio_transcription audio_speech rerank moderation ocr search video_generation'

hl_init_paths() {
  HL_CONF="$HOME/.config/homelab-models"
  HL_SHARE="$HOME/.local/share/homelab-models"
  HL_HELPER="$HOME/.local/bin/homelab-model-key"
  HL_PLIST="$HOME/Library/LaunchAgents/$HL_LABEL.plist"
  HL_LOG="$HOME/Library/Logs/homelab-models.log"
  HL_ZSHRC="${ZDOTDIR:-$HOME}/.zshrc"
  HL_CLAUDE_SETTINGS="$HOME/.claude/settings.json"
  HL_CODEX_CONFIG="${CODEX_HOME:-$HOME/.codex}/config.toml"
  HL_CURSOR_SETTINGS="$HOME/Library/Application Support/Cursor/User/settings.json"
  HL_CA="$HL_CONF/web-ca.crt"
  HL_CA_BUNDLE="$HL_CONF/ca-bundle.pem"
  HL_ENV="$HL_CONF/env.sh"
  HL_STATE="$HL_CONF/state"
  HL_MODELS_CACHE="$HL_CONF/models.txt"
  HL_BACKUP_DIR=""
}

# ---------------------------------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------------------------------
HL_PROBLEMS=0
hl_say() { printf '%s\n' "$*"; }
hl_ok() { printf '  ok    %s\n' "$*"; }
hl_warn() { printf '  WARN  %s\n' "$*"; HL_PROBLEMS=$((HL_PROBLEMS + 1)); }
hl_fail() { printf '  FAIL  %s\n' "$*"; HL_PROBLEMS=$((HL_PROBLEMS + 1)); }
hl_fix() { printf '  fix   %s\n' "$*"; }
hl_die() { printf 'error: %s\n' "$*" >&2; exit 1; }
hl_log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# Is there a terminal to ask on? (/dev/tty exists even without one, so try to open it)
hl_have_tty() { { : </dev/tty; } 2>/dev/null; }

# Ask a yes/no question on the terminal (also under `curl | bash`, whose stdin is the script). --yes answers yes.
hl_confirm() {
  local answer
  [ "${HL_YES:-0}" = 1 ] && return 0
  hl_have_tty || return 1
  printf '%s [y/N] ' "$1" >/dev/tty
  IFS= read -r answer </dev/tty || return 1
  case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# Run a command with a time limit (macOS has no timeout(1)).
hl_timeout() {
  local secs=$1; shift
  perl -e 'alarm shift @ARGV; exec @ARGV or exit 127' "$secs" "$@"
}

# ---------------------------------------------------------------------------------------------------------------------
# Pure logic (no network, no Keychain): tested on Linux by tests/run.sh
# ---------------------------------------------------------------------------------------------------------------------

# Chat model names from /v1/models JSON ($1) and /model/info JSON ($2, may be empty): one per line, sorted, no
# wildcards, no route whose mode is not chat.
hl_filter_models() {
  local models_json=$1 info_json=${2:-}
  [ -n "$info_json" ] || info_json='{"data":[]}'
  jq -r --argjson info "$info_json" --arg nonchat "$HL_NON_CHAT_MODES" '
    ($nonchat | split(" ")) as $bad
    | ([$info.data[]? | select((.model_info.mode // "chat") as $m | $bad | index($m)) | .model_name]) as $drop
    | [.data[]?.id | select(type == "string" and . != "" and (contains("*") | not))]
    | map(select(. as $id | $drop | index($id) | not))
    | unique[]' <<<"$models_json"
}

# Is $1 one of the lines of $2?
hl_in_list() {
  local needle=$1 list=$2 line
  while IFS= read -r line; do [ "$line" = "$needle" ] && return 0; done <<<"$list"
  return 1
}

# The model to use: $1 if it is in the list $3, else $2 if it is, else the first in the list.
hl_pick_model() {
  local want=$1 fallback=$2 list=$3
  if [ -n "$want" ] && hl_in_list "$want" "$list"; then printf '%s\n' "$want"
  elif hl_in_list "$fallback" "$list"; then printf '%s\n' "$fallback"
  else printf '%s\n' "$list" | head -n 1
  fi
}

# Lines of /etc/hosts (file $1) that pin a *.nghodki.ai name: "lineno:text", uncommented lines only.
hl_hosts_pins() {
  awk '{ line = $0; sub(/#.*/, "", line) } line ~ /(^|[[:space:].])nghodki\.ai([[:space:]]|$)/ { print NR ":" $0 }' "$1"
}

# /etc/hosts ($1) with those lines commented out.
hl_hosts_unpin() {
  awk '{ line = $0; sub(/#.*/, "", line) }
       line ~ /(^|[[:space:].])nghodki\.ai([[:space:]]|$)/ { print "# disabled by homelab install-mac.sh: " $0; next }
       { print }' "$1"
}

# Claude Code settings ($1, JSON text) with our apiKeyHelper and /model picker rows for the models ($3, lines).
# Every other key is kept as it is (including the claudeCode.* keys some Macs have there).
hl_claude_settings_apply() {
  local settings=$1 helper=$2 models=$3 default=$4
  [ -n "$settings" ] || settings='{}'
  jq --arg helper "$helper" --arg models "$models" --arg default "$default" --arg tag "$HL_PICKER_TAG" '
    ($models | split("\n") | map(select(. != ""))) as $m
    | ([$default | select(. as $d | $m | index($d))] + ($m - [$default])) as $ordered
    | .apiKeyHelper = $helper
    | .modelPicker = {
        replaceBuiltInOptions: true,
        options: [$ordered[] | {model: ., label: ., description:
          ($tag + (if . == $default then " (default)" else "" end) + ": an on-demand model wakes in about 5 min")}]
      }' <<<"$settings"
}

# Is the picker in these settings ours (every row carries our tag), or absent?
hl_claude_picker_owner() {
  jq -r --arg tag "$HL_PICKER_TAG" '
    if .modelPicker == null then "none"
    elif ([.modelPicker.options[]? | (.description // "") | startswith($tag)] | all) then "ours"
    else "foreign" end' <<<"$1"
}

# Claude Code settings without what hl_claude_settings_apply added.
hl_claude_settings_remove() {
  jq --arg tag "$HL_PICKER_TAG" '
    (if (.apiKeyHelper // "" | test("homelab-model-key")) then del(.apiKeyHelper) else . end)
    | (if .modelPicker != null and ([.modelPicker.options[]? | (.description // "") | startswith($tag)] | all)
       then del(.modelPicker) else . end)' <<<"$1"
}

# Cursor's settings.json ($1) with the Claude Code extension's environment pointed at LiteLLM: https base URL, the web
# CA, model names that exist ($4, lines; else $5), and no API key in the file (apiKeyHelper reads the Keychain).
# Only touches claudeCode.environmentVariables, and only when the extension is already configured for a gateway or
# $6 = force. Never touches an extension set up for Bedrock/Vertex.
hl_cursor_env_apply() {
  local settings=$1 base=$2 ca=$3 models=$4 default=$5 force=${6:-}
  jq --arg base "$base" --arg ca "$ca" --arg models "$models" --arg default "$default" --arg force "$force" '
    ($models | split("\n") | map(select(. != ""))) as $m
    | (.["claudeCode.environmentVariables"] // []) as $env
    | ($env | map({key: .name, value: .value}) | from_entries) as $e
    | if ($e.CLAUDE_CODE_USE_BEDROCK // $e.CLAUDE_CODE_USE_VERTEX // $e.CLAUDE_CODE_USE_FOUNDRY // "") != "" then .
      elif ($e.ANTHROPIC_BASE_URL // "") == "" and $force != "force" then .
      else
        def model($k): ($e[$k] // "") as $v | if ($m | index($v)) then $v else $default end;
        ["ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"] as $mk
        | ["ANTHROPIC_BASE_URL", "NODE_EXTRA_CA_CERTS", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
           "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_CUSTOM_MODEL_OPTION"] as $drop
        | .["claudeCode.environmentVariables"] =
            ([$env[] | select(.name as $n | ($drop + $mk) | index($n) | not)]
             + [{name: "ANTHROPIC_BASE_URL", value: $base}, {name: "NODE_EXTRA_CA_CERTS", value: $ca}]
             + [$mk[] | select(. == "ANTHROPIC_MODEL" | not) | {name: ., value: model(.)}]
             + (if ($e.ANTHROPIC_MODEL // "") != "" then [{name: "ANTHROPIC_MODEL", value: model("ANTHROPIC_MODEL")}] else [] end))
      end' <<<"$settings"
}

# Does Cursor's settings.json ($1) still hold an API key or a non-https base URL for the Claude Code extension?
hl_cursor_env_issues() {
  jq -r --arg base "$2" '
    ((.["claudeCode.environmentVariables"] // []) | map({key: .name, value: .value}) | from_entries) as $e
    | if ($e.CLAUDE_CODE_USE_BEDROCK // "") != "" then "bedrock"
      elif ($e.ANTHROPIC_BASE_URL // "") == "" then "none"
      else ([ (if ($e.ANTHROPIC_API_KEY // $e.ANTHROPIC_AUTH_TOKEN // "") != "" then "key-in-file" else empty end),
              (if ($e.ANTHROPIC_BASE_URL | rtrimstr("/")) != ($base | rtrimstr("/")) then "base-url" else empty end),
              (if ($e.NODE_EXTRA_CA_CERTS // "") == "" then "no-ca" else empty end) ] | join(" ")) end' <<<"$1"
}

# Codex config.toml (file $1) with our provider: a block at the top for the two top-level keys (earlier top-level
# `model` and `model_provider` lines are commented out, so uninstall can restore them) and a block at the end with the
# provider table. The key comes from the Keychain through the provider's auth command.
hl_codex_config_apply() {
  local file=$1 base=$2 model=$3 helper=$4
  hl_codex_config_remove "$file" | awk -v base="$base" -v model="$model" -v helper="$helper" \
    -v b="$HL_MARK_BEGIN" -v e="$HL_MARK_END" '
    BEGIN {
      print b " (managed by homelab install-mac.sh; the key is read from the Keychain)"
      print "model = \"" model "\""
      print "model_provider = \"homelab\""
      print e
      top = 1
    }
    /^[[:space:]]*\[/ { top = 0 }
    top && /^[[:space:]]*(model|model_provider)[[:space:]]*=/ { print "# homelab-models was: " $0; next }
    { print }
    END {
      print ""
      print b " providers"
      print "[model_providers.homelab]"
      print "name = \"Homelab LiteLLM\""
      print "base_url = \"" base "/v1\""
      print "wire_api = \"responses\""
      print ""
      print "[model_providers.homelab.auth]"
      print "command = \"" helper "\""
      print "args = [\"codex\"]"
      print e
    }' | hl_squeeze_blank_tail
}

# Codex config.toml (file $1) without our blocks, with the commented-out top-level keys restored.
hl_codex_config_remove() {
  [ -f "$1" ] || return 0
  awk -v b="$HL_MARK_BEGIN" -v e="$HL_MARK_END" '
    index($0, b) == 1 { skip = 1; next }
    skip && index($0, e) == 1 { skip = 0; next }
    skip { next }
    /^# homelab-models was: / { sub(/^# homelab-models was: /, ""); print; next }
    { print }' "$1" | hl_squeeze_blank_tail
}

# The model our Codex block selects (empty if none).
hl_codex_managed_model() {
  [ -f "$1" ] || return 0
  awk -v b="$HL_MARK_BEGIN" -v e="$HL_MARK_END" '
    index($0, b) == 1 { inb = 1; next } inb && index($0, e) == 1 { exit }
    inb && /^model[[:space:]]*=/ { v = $0; sub(/^[^"]*"/, "", v); sub(/".*$/, "", v); print v; exit }' "$1"
}

# Is there a [model_providers.homelab] table outside our block (someone else's)?
hl_codex_foreign_provider() {
  [ -f "$1" ] || return 1
  hl_codex_config_remove "$1" | grep -qE '^[[:space:]]*\[model_providers\.homelab(\.auth)?\]'
}

hl_squeeze_blank_tail() {
  awk '{ lines[NR] = $0 } END { n = NR; while (n > 0 && lines[n] == "") n--; for (i = 1; i <= n; i++) print lines[i] }'
}

# Shell startup file ($1): our block appended (sourcing env.sh), the old hand-written exports for Claude Code removed
# (`export ANTHROPIC_...=` lines outside the block; their values move to the Keychain and env.sh). Comments and all other
# lines are kept.
hl_zshrc_apply() {
  local file=$1 envfile=$2
  hl_zshrc_remove "$file" | awk '
    /^[[:space:]]*export[[:space:]]+ANTHROPIC_(AUTH_TOKEN|API_KEY|BASE_URL|MODEL|SMALL_FAST_MODEL|DEFAULT_(OPUS|SONNET|HAIKU|FABLE)_MODEL|CUSTOM_MODEL_OPTION[A-Z_]*)=/ { next }
    { print }' | hl_squeeze_blank_tail
  printf '\n%s\n' "$HL_MARK_BEGIN"
  printf '%s\n' "# Claude Code and Codex use the homelab LiteLLM: install-mac.sh (homelab repo, tools/dev-setup). Keys are in the Keychain."
  printf '[ -r "%s" ] && . "%s"\n' "$envfile" "$envfile"
  printf '%s\n' "$HL_MARK_END"
}

hl_zshrc_remove() {
  [ -f "$1" ] || return 0
  awk -v b="$HL_MARK_BEGIN" -v e="$HL_MARK_END" '
    index($0, b) == 1 { skip = 1; next }
    skip && index($0, e) == 1 { skip = 0; next }
    !skip { print }' "$1" | hl_squeeze_blank_tail
}

# Names of the old hand-written exports in a startup file ($1) that hl_zshrc_apply would remove.
hl_zshrc_legacy_names() {
  [ -f "$1" ] || return 0
  hl_zshrc_remove "$1" | sed -nE 's/^[[:space:]]*export[[:space:]]+(ANTHROPIC_(AUTH_TOKEN|API_KEY|BASE_URL|MODEL|SMALL_FAST_MODEL|DEFAULT_(OPUS|SONNET|HAIKU|FABLE)_MODEL|CUSTOM_MODEL_OPTION[A-Z_]*))=.*/\1/p'
}

# The value of a model-name export in a startup file (never used for keys).
hl_zshrc_model_value() {
  [ -f "$1" ] || return 0
  hl_zshrc_remove "$1" | sed -nE "s/^[[:space:]]*export[[:space:]]+$2=[\"']?([A-Za-z0-9._:\/-]+)[\"']?[[:space:]]*\$/\\1/p" | tail -n 1
}

# env.sh, sourced by the shell block: POSIX sh, so bash and zsh can read it. No secrets in it.
hl_env_render() {
  local base=$1 ca=$2 bundle=$3 opus=$4 sonnet=$5 haiku=$6
  cat <<ENV
# Written by homelab install-mac.sh (and its sync agent). Do not edit: run install-mac.sh --repair instead.
# No keys here: Claude Code reads its key with apiKeyHelper, Codex with its provider's auth command (both: Keychain).
export ANTHROPIC_BASE_URL="$base"
export NODE_EXTRA_CA_CERTS="$ca"
export CODEX_CA_CERTIFICATE="$bundle"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$opus"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$sonnet"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$haiku"
# A key in the environment would win over apiKeyHelper
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
ENV
}

# A value from env.sh ($1) by name ($2).
hl_env_value() {
  [ -f "$1" ] || return 0
  sed -nE "s/^export $2=\"([^\"]*)\"\$/\\1/p" "$1" | tail -n 1
}

# The LaunchAgent that runs the sync every 5 minutes.
hl_plist_render() {
  local script=$1 log=$2
  cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$HL_LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$script</string><string>--sync</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>300</integer>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict>
</plist>
PLIST
}

# The Keychain helper: prints the key for one tool (claude-code, cursor, codex).
hl_helper_render() {
  cat <<HELPER
#!/bin/sh
# Prints the homelab LiteLLM key for one tool from the login Keychain (homelab install-mac.sh). Used by Claude Code's
# apiKeyHelper and Codex's provider auth command. Usage: homelab-model-key claude-code|cursor|codex
exec /usr/bin/security find-generic-password -s "$HL_KC_SERVICE" -a "\${1:-claude-code}" -w
HELPER
}

# ---------------------------------------------------------------------------------------------------------------------
# Files: atomic writes with a backup of what was there
# ---------------------------------------------------------------------------------------------------------------------
hl_backup() {
  local file=$1 dest
  [ -e "$file" ] || return 0
  if [ -z "$HL_BACKUP_DIR" ]; then
    HL_BACKUP_DIR="$HL_SHARE/backups/$(date +%Y%m%d-%H%M%S)-$$"
    mkdir -p "$HL_BACKUP_DIR" && chmod 700 "$HL_SHARE/backups" "$HL_BACKUP_DIR"
  fi
  dest="$HL_BACKUP_DIR/$(printf '%s' "${file#"$HOME"/}" | tr '/ ' '__')"
  cp -p "$file" "$dest"
}

# Write stdin to $1 if it differs: backup, temporary file in the same folder, then rename. Keeps the file's mode.
# Returns 0 if written, 1 if unchanged, 2 on error.
hl_write() {
  local file=$1 mode=${2:-} dir tmp
  dir=$(dirname "$file")
  mkdir -p "$dir" || return 2
  tmp=$(mktemp "$dir/.homelab-models.XXXXXX") || return 2
  cat >"$tmp" || { rm -f "$tmp"; return 2; }
  if [ -f "$file" ] && cmp -s "$tmp" "$file"; then rm -f "$tmp"; return 1; fi
  if [ -f "$file" ]; then
    hl_backup "$file" || { rm -f "$tmp"; return 2; }
    [ -n "$mode" ] || mode=$(stat -c '%a' "$file" 2>/dev/null || stat -f '%Lp' "$file")
  fi
  chmod "${mode:-644}" "$tmp" && mv -f "$tmp" "$file" || { rm -f "$tmp"; return 2; }
  return 0
}

hl_state_get() { [ -f "$HL_STATE" ] && sed -n "s/^$1=//p" "$HL_STATE" | tail -n 1; }
hl_state_set() {
  local key=$1 value=$2
  { [ -f "$HL_STATE" ] && grep -v "^$key=" "$HL_STATE"; printf '%s=%s\n' "$key" "$value"; } | hl_write "$HL_STATE" 600
  return 0
}

# ---------------------------------------------------------------------------------------------------------------------
# Keychain and LiteLLM (the key never reaches argv, a file or the terminal)
# ---------------------------------------------------------------------------------------------------------------------
hl_key_get() {
  if [ -n "${HL_TEST_KEYDIR:-}" ]; then cat "$HL_TEST_KEYDIR/$1" 2>/dev/null; return; fi
  /usr/bin/security find-generic-password -s "$HL_KC_SERVICE" -a "$1" -w 2>/dev/null
}

# Store key ($2) for account ($1). `security -i` reads the command from stdin, so the key isn't in any process's argv.
hl_key_put() {
  case "$2" in *[!A-Za-z0-9._-]*|"") hl_say "  that doesn't look like a LiteLLM key (letters, digits, . _ - only)"; return 1 ;; esac
  if [ -n "${HL_TEST_KEYDIR:-}" ]; then mkdir -p "$HL_TEST_KEYDIR"; (umask 077; printf '%s' "$2" >"$HL_TEST_KEYDIR/$1"); return; fi
  printf 'add-generic-password -U -s %s -a %s -l "homelab LiteLLM key (%s)" -w %s\n' "$HL_KC_SERVICE" "$1" "$1" "$2" \
    | /usr/bin/security -i >/dev/null
}

hl_key_delete() {
  if [ -n "${HL_TEST_KEYDIR:-}" ]; then rm -f "$HL_TEST_KEYDIR/$1"; return; fi
  /usr/bin/security delete-generic-password -s "$HL_KC_SERVICE" -a "$1" >/dev/null 2>&1
}

# GET $HL_BASE$1 with key $2; body on stdout, HTTP status in HL_HTTP. The header goes to curl through stdin.
hl_get() {
  local path=$1 key=$2 out
  out=$(printf 'header = "Authorization: Bearer %s"\n' "$key" \
    | curl -sS -m "${3:-20}" -K - -w '\n%{http_code}' "$HL_BASE$path" 2>/dev/null) || { HL_HTTP=000; return 1; }
  HL_HTTP=${out##*$'\n'}
  printf '%s' "${out%$'\n'*}"
  [ "$HL_HTTP" = 200 ]
}

hl_key_valid() { hl_get /v1/models "$1" >/dev/null; }

# The key's alias, from LiteLLM's /key/info (a key may read its own info).
hl_key_alias() {
  hl_get /key/info "$1" 10 | jq -r '.info.key_alias // empty' 2>/dev/null
}

# A key to read the model list with: the first tool account that has a working one.
hl_any_key() {
  local acct key
  for acct in claude-code codex cursor; do
    key=$(hl_key_get "$acct") || continue
    [ -n "$key" ] && { printf '%s' "$key"; return 0; }
  done
  return 1
}

# The chat models the key may use (one per line).
hl_fetch_models() {
  local key=$1 models info
  models=$(hl_get /v1/models "$key") || return 1
  info=$(hl_get /v1/model/info "$key") || info=''
  printf '%s' "$info" | jq -e . >/dev/null 2>&1 || info=''
  hl_filter_models "$models" "$info"
}

# ---------------------------------------------------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------------------------------------------------
hl_detect_tools() {
  local t=""
  { command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ]; } && t="$t claude"
  { [ -d /Applications/Cursor.app ] || [ -d "$HOME/Applications/Cursor.app" ] || [ -f "$HL_CURSOR_SETTINGS" ]; } && t="$t cursor"
  # Codex only when the CLI or app is installed (a config.toml alone is often left over)
  { command -v codex >/dev/null 2>&1 || [ -d /Applications/Codex.app ]; } && t="$t codex"
  printf '%s' "${t# }"
}

hl_want() { case " $HL_TOOLS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# The Keychain account each tool reads (Cursor's Claude Code extension runs the same CLI, so it reads claude-code)
hl_accounts() {
  local a=""
  { hl_want claude || hl_want cursor; } && a="claude-code"
  hl_want codex && a="$a codex"
  printf '%s' "${a# }"
}

hl_step_hosts() {
  local pins
  hl_say "/etc/hosts"
  pins=$(hl_hosts_pins /etc/hosts)
  if [ -z "$pins" ]; then hl_ok "no *.nghodki.ai pins (names come from the home DNS over Tailscale)"; return; fi
  hl_warn "/etc/hosts pins names that the home DNS should answer; a stale pin sends them to an old front door:"
  printf '%s\n' "$pins" | sed 's/^/          /'
  [ "$HL_MODE" = check ] && return
  hl_say "  Commenting them out needs sudo (macOS asks for your password). A copy is kept as /etc/hosts.homelab-backup-<time>."
  if hl_confirm "  Comment out these lines in /etc/hosts?"; then
    local tmp; tmp=$(mktemp) || return
    hl_hosts_unpin /etc/hosts >"$tmp"
    if sudo cp -p /etc/hosts "/etc/hosts.homelab-backup-$(date +%Y%m%d-%H%M%S)" && sudo cp "$tmp" /etc/hosts; then
      sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder 2>/dev/null
      hl_fix "pins commented out, DNS cache flushed"; HL_PROBLEMS=$((HL_PROBLEMS - 1))
    else hl_fail "could not change /etc/hosts"
    fi
    rm -f "$tmp"
  else hl_say "  left as it is"
  fi
}

hl_step_reach() {
  local host code
  hl_say "Endpoint $HL_BASE"
  case "$HL_BASE" in
    https://*) ;;
    http://*) hl_warn "plain http: keys and prompts cross the network unencrypted; use --base-url https://${HL_BASE#http://}" ;;
    *) hl_die "--base-url must start with https:// or http://" ;;
  esac
  host=${HL_BASE#*://}; host=${host%%/*}
  if ! dscacheutil -q host -a name "$host" 2>/dev/null | grep -q ip_address; then
    hl_fail "$host does not resolve: is Tailscale connected (and its DNS on)?"; return 1
  fi
  code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://$host/health/liveliness")
  if [ "$code" = 200 ]; then hl_ok "$host answers"; else hl_fail "$host: http://$host/health/liveliness gave $code"; return 1; fi
}

# The web CA: downloaded, checked against the pinned fingerprint, kept in ~/.config/homelab-models for Node
# (NODE_EXTRA_CA_CERTS) and Codex (a bundle of the macOS roots plus the CA), and trusted in the login Keychain.
hl_step_ca() {
  local url tmp fp have=0
  hl_say "Homelab web CA"
  if [ -f "$HL_CA" ] && [ "$(hl_ca_fp "$HL_CA")" = "$HL_CA_SHA256" ]; then have=1; hl_ok "$HL_CA (fingerprint checked)"; fi
  if [ "$have" = 0 ]; then
    if [ "$HL_MODE" = check ]; then hl_warn "$HL_CA missing or wrong"; else
      tmp=$(mktemp) || return 1
      for url in $HL_CA_URLS; do
        curl -fsS -m 20 -o "$tmp" "$url" 2>/dev/null || continue
        fp=$(hl_ca_fp "$tmp")
        if [ "$fp" = "$HL_CA_SHA256" ]; then hl_write "$HL_CA" 644 <"$tmp"; have=1; hl_fix "downloaded from $url, fingerprint matches"; break; fi
        hl_warn "$url: fingerprint $fp is not the pinned one; ignored"
      done
      rm -f "$tmp"
      [ "$have" = 1 ] || { hl_fail "could not get the web CA"; return 1; }
    fi
  fi
  if [ "$have" = 1 ] && [ "$HL_MODE" != check ]; then
    { /usr/bin/security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain; cat "$HL_CA"; } \
      | hl_write "$HL_CA_BUNDLE" 644
  fi
  # /usr/bin/curl verifies with the macOS trust store: the test for Keychain trust (Cursor, Safari, Electron apps)
  if /usr/bin/curl -s -o /dev/null -m 10 "https://${HL_BASE#*://}/health/liveliness" 2>/dev/null; then
    hl_ok "trusted by macOS (Keychain)"
  elif [ "$HL_MODE" = check ] || [ "$have" = 0 ]; then
    hl_warn "macOS does not trust the web CA yet (apps that use the Keychain fail on https)"
  else
    hl_say "  macOS doesn't trust the web CA yet. Adding it to your login keychain as trusted for SSL: macOS shows"
    hl_say "  a dialog asking for your login password (\"You are making changes to your Certificate Trust Settings\")."
    if hl_confirm "  Trust the homelab web CA (name-constrained to nghodki.ai) in your login keychain?"; then
      if /usr/bin/security add-trusted-cert -r trustRoot -p ssl -k "$HOME/Library/Keychains/login.keychain-db" "$HL_CA"; then
        hl_fix "trusted in the login keychain"
      else hl_warn "not trusted (cancelled, or no GUI session: run this in Terminal on the Mac)"
      fi
    else hl_warn "skipped: Node tools still work (NODE_EXTRA_CA_CERTS), Keychain-based apps don't"
    fi
  fi
}

hl_ca_fp() { /usr/bin/openssl x509 -in "$1" -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//; s/://g' | tr 'a-f' 'A-F'; }

# One key per account, in the Keychain. A working key in the old shell exports (claude-code) is moved there.
hl_step_keys() {
  local acct key alias legacy
  hl_say "API keys (Keychain service $HL_KC_SERVICE)"
  for acct in $(hl_accounts); do
    key=$(hl_key_get "$acct")
    if [ -n "$key" ] && hl_key_valid "$key"; then
      alias=$(hl_key_alias "$key"); hl_ok "$acct: works${alias:+ (LiteLLM key alias $alias)}"; continue
    fi
    if [ -n "$key" ]; then hl_warn "$acct: the stored key is refused (HTTP $HL_HTTP)"; else hl_warn "$acct: no key stored"; fi
    [ "$HL_MODE" = check ] && continue
    key=""
    if [ "$acct" = claude-code ]; then
      legacy=$(hl_legacy_claude_key)
      if [ -n "$legacy" ] && hl_key_valid "$legacy"; then key=$legacy; hl_fix "$acct: using the key from the old shell exports"; fi
    fi
    while [ -z "$key" ]; do
      if ! hl_have_tty; then hl_fail "$acct: no terminal to ask for a key"; break; fi
      hl_say "  Create a key with alias \"$acct\" at https://litellm-admin.nghodki.ai (Virtual Keys, + Create New Key)."
      if [ "$acct" != claude-code ] && [ -n "$(hl_key_get claude-code)" ]; then
        printf '  Paste the %s key (hidden), or press Enter to reuse the claude-code key: ' "$acct" >/dev/tty
      else
        printf '  Paste the %s key (hidden), or press Enter to skip: ' "$acct" >/dev/tty
      fi
      IFS= read -r -s key </dev/tty; printf '\n' >/dev/tty
      if [ -z "$key" ]; then
        [ "$acct" != claude-code ] && key=$(hl_key_get claude-code)
        [ -n "$key" ] || break
      fi
      if ! hl_key_valid "$key"; then hl_say "  LiteLLM refused it (HTTP $HL_HTTP); try again"; key=""; fi
    done
    [ -n "$key" ] || { hl_fail "$acct: no key; this tool is not configured"; continue; }
    if hl_key_put "$acct" "$key"; then hl_fix "$acct: stored in the Keychain"; HL_PROBLEMS=$((HL_PROBLEMS - 1)); else hl_fail "$acct: Keychain refused the key (locked? run in Terminal)"; fi
  done
  key=""; legacy=""
}

# The token the old ~/.zshrc exports gave Claude Code (evaluated by zsh, never printed). Also looks in this script's
# backups of ~/.zshrc, newest first, for a run that moved the exports out but couldn't reach the Keychain.
hl_legacy_claude_key() {
  local f key
  for f in "$HL_ZSHRC" $(ls -1r "$HL_SHARE"/backups/*/.zshrc 2>/dev/null); do
    hl_zshrc_legacy_names "$f" | grep -qE 'ANTHROPIC_(AUTH_TOKEN|API_KEY)' || continue
    # shellcheck disable=SC2016  # expanded by zsh
    key=$(zsh -c '. "$1" >/dev/null 2>&1; printf %s "${ANTHROPIC_AUTH_TOKEN:-$ANTHROPIC_API_KEY}"' zsh "$f" </dev/null 2>/dev/null)
    [ -n "$key" ] && { printf '%s' "$key"; return 0; }
  done
  return 0
}

hl_step_helper() {
  hl_say "Keychain helper $HL_HELPER"
  if [ "$HL_MODE" = check ]; then
    if [ -x "$HL_HELPER" ] && hl_helper_render | cmp -s - "$HL_HELPER"; then hl_ok "installed"; else hl_warn "missing or changed"; fi
    return
  fi
  hl_helper_render | hl_write "$HL_HELPER" 755; case $? in 0) hl_fix "installed" ;; 1) hl_ok "installed" ;; *) hl_fail "could not write it" ;; esac
}

# The models, from LiteLLM when it answers, else the last list we saw.
hl_step_models() {
  local key list
  hl_say "Models"
  key=$(hl_any_key) || key=""
  if [ -n "$key" ] && list=$(hl_fetch_models "$key") && [ -n "$list" ]; then
    HL_MODELS=$list
    printf '%s\n' "$list" | hl_write "$HL_MODELS_CACHE" 644
    hl_ok "$(printf '%s' "$list" | tr '\n' ' ')"
  elif [ -f "$HL_MODELS_CACHE" ]; then
    HL_MODELS=$(cat "$HL_MODELS_CACHE"); hl_warn "LiteLLM didn't list models; using the last list"
  else
    HL_MODELS=$HL_DEFAULT_MODEL; hl_warn "LiteLLM didn't list models; assuming $HL_DEFAULT_MODEL"
  fi
  key=""
  hl_in_list "$HL_DEFAULT_MODEL" "$HL_MODELS" || hl_warn "the default model $HL_DEFAULT_MODEL is not in the list"
}

hl_step_env() {
  local opus sonnet haiku
  # Keep a model someone picked if it still exists; otherwise the default
  opus=$(hl_pick_model "$(hl_env_value "$HL_ENV" ANTHROPIC_DEFAULT_OPUS_MODEL)" "$HL_DEFAULT_MODEL" "$HL_MODELS")
  sonnet=$(hl_pick_model "$(hl_env_value "$HL_ENV" ANTHROPIC_DEFAULT_SONNET_MODEL)" "$HL_DEFAULT_MODEL" "$HL_MODELS")
  haiku=$(hl_env_value "$HL_ENV" ANTHROPIC_DEFAULT_HAIKU_MODEL)
  [ -n "$haiku" ] || haiku=$(hl_zshrc_model_value "$HL_ZSHRC" ANTHROPIC_DEFAULT_HAIKU_MODEL)
  haiku=$(hl_pick_model "$haiku" "$HL_DEFAULT_MODEL" "$HL_MODELS")
  hl_env_render "$HL_BASE" "$HL_CA" "$HL_CA_BUNDLE" "$opus" "$sonnet" "$haiku" | hl_write "$HL_ENV" 644
}

hl_step_shell() {
  local legacy
  hl_say "Shell ($HL_ZSHRC)"
  legacy=$(hl_zshrc_legacy_names "$HL_ZSHRC" | tr '\n' ' ')
  if [ "$HL_MODE" = check ]; then
    if [ -f "$HL_ZSHRC" ] && grep -qF "$HL_MARK_BEGIN" "$HL_ZSHRC"; then hl_ok "homelab block present"; else hl_warn "no homelab block"; fi
    [ -z "$legacy" ] || hl_warn "old exports to migrate: $legacy"
    [ -f "$HL_ENV" ] && [ "$(hl_env_value "$HL_ENV" ANTHROPIC_BASE_URL)" = "$HL_BASE" ] && hl_ok "env.sh points at $HL_BASE" || hl_warn "env.sh missing or points elsewhere"
    return
  fi
  hl_step_env
  # The old exports hold the key: they go only once the Keychain has it
  if printf '%s' "$legacy" | grep -qE 'ANTHROPIC_(AUTH_TOKEN|API_KEY)' && [ -z "$(hl_key_get claude-code)" ]; then
    hl_warn "the old exports hold the only copy of the key and the Keychain has none: $HL_ZSHRC left as it is"; return
  fi
  hl_zshrc_apply "$HL_ZSHRC" "$HL_ENV" | hl_write "$HL_ZSHRC"
  case $? in
    0) hl_fix "block written${legacy:+; moved out of the file: $legacy(keys now in the Keychain, models in env.sh)}" ;;
    1) hl_ok "block present" ;;
    *) hl_fail "could not write $HL_ZSHRC" ;;
  esac
}

hl_step_claude() {
  local cur owner new
  hl_say "Claude Code ($HL_CLAUDE_SETTINGS)"
  cur='{}'
  if [ -f "$HL_CLAUDE_SETTINGS" ]; then
    cur=$(cat "$HL_CLAUDE_SETTINGS")
    jq -e . >/dev/null 2>&1 <<<"$cur" || { hl_fail "not valid JSON; fix it by hand (left as it is)"; return; }
  fi
  owner=$(hl_claude_picker_owner "$cur")
  local helper_cur; helper_cur=$(jq -r '.apiKeyHelper // empty' <<<"$cur")
  if [ "$HL_MODE" = check ]; then
    case "$helper_cur" in *homelab-model-key*) hl_ok "apiKeyHelper reads the Keychain" ;; "") hl_warn "no apiKeyHelper" ;; *) hl_warn "apiKeyHelper is someone else's: $helper_cur" ;; esac
    case "$owner" in ours) hl_ok "/model picker: $(jq -r '[.modelPicker.options[].model] | join(" ")' <<<"$cur")" ;; none) hl_warn "/model picker not set" ;; *) hl_warn "/model picker set by someone else" ;; esac
    return
  fi
  if { [ "$owner" = foreign ] || { [ -n "$helper_cur" ] && [ "${helper_cur#*homelab-model-key}" = "$helper_cur" ]; }; } && [ "$HL_MODE" != repair ]; then
    hl_say "  settings.json already has its own apiKeyHelper or /model picker."
    hl_confirm "  Replace them (a backup is kept)?" || { hl_warn "left as it is"; return; }
  fi
  new=$(hl_claude_settings_apply "$cur" "$HL_HELPER claude-code" "$HL_MODELS" "$HL_DEFAULT_MODEL") || { hl_fail "jq failed"; return; }
  jq . <<<"$new" | hl_write "$HL_CLAUDE_SETTINGS"
  case $? in 0) hl_fix "apiKeyHelper and /model picker written (other keys untouched)" ;; 1) hl_ok "up to date" ;; *) hl_fail "could not write" ;; esac
  hl_state_set claude managed
}

# Cursor's own chat can't use LiteLLM (Cursor calls custom endpoints from its servers, which can't reach the tailnet), so
# this configures the Claude Code extension inside Cursor (and Codex's, which reads ~/.codex/config.toml anyway).
hl_step_cursor() {
  local cur issues new force=""
  hl_say "Cursor ($HL_CURSOR_SETTINGS)"
  if [ ! -f "$HL_CURSOR_SETTINGS" ]; then hl_ok "no settings.json yet (nothing to change)"; return; fi
  cur=$(cat "$HL_CURSOR_SETTINGS")
  if ! jq -e . >/dev/null 2>&1 <<<"$cur"; then
    hl_warn "settings.json has comments or isn't plain JSON: set the Claude Code extension by hand (page, Cursor section)"; return
  fi
  issues=$(hl_cursor_env_issues "$cur" "$HL_BASE")
  case "$issues" in
    bedrock) hl_ok "the Claude Code extension uses Bedrock here: left alone"; return ;;
    none) if [ "$HL_MODE" = check ]; then hl_ok "the Claude Code extension has no gateway settings (it uses ~/.claude/settings.json)"; return; fi
          force=force ;;
    "") hl_ok "Claude Code extension: $HL_BASE, CA set, no key in the file" ;;
    *) hl_warn "Claude Code extension: $issues" ;;
  esac
  [ "$HL_MODE" = check ] && return
  # The key in the file is dropped only once the Keychain helper works (else the extension would lose its credential)
  if [ -z "$(hl_key_get claude-code)" ]; then hl_warn "no claude-code key in the Keychain: Cursor's settings left as they are"; return; fi
  new=$(hl_cursor_env_apply "$cur" "$HL_BASE" "$HL_CA" "$HL_MODELS" "$HL_DEFAULT_MODEL" "$force") || { hl_fail "jq failed"; return; }
  jq . <<<"$new" | hl_write "$HL_CURSOR_SETTINGS"
  case $? in 0) hl_fix "Claude Code extension: https, CA, model names; key now from the Keychain (Cursor reloads it live)" ;; 1) ;; *) hl_fail "could not write" ;; esac
  hl_state_set cursor managed
}

hl_step_codex() {
  local new managed
  hl_say "Codex ($HL_CODEX_CONFIG)"
  managed=$(hl_codex_managed_model "$HL_CODEX_CONFIG")
  if [ "$HL_MODE" = check ]; then
    if [ -n "$managed" ]; then
      if hl_in_list "$managed" "$HL_MODELS"; then hl_ok "provider homelab, model $managed"; else hl_warn "model $managed is no longer served"; fi
      grep -q "base_url = \"$HL_BASE/v1\"" "$HL_CODEX_CONFIG" && hl_ok "base_url $HL_BASE/v1" || hl_warn "base_url is not $HL_BASE/v1"
    else hl_warn "no homelab provider"
    fi
    command -v codex >/dev/null 2>&1 || hl_say "  (codex is not installed: npm i -g @openai/codex, or brew install codex)"
    return
  fi
  if hl_codex_foreign_provider "$HL_CODEX_CONFIG"; then
    hl_fail "config.toml already has its own [model_providers.homelab]; rename it, then run again"; return
  fi
  mkdir -p "$(dirname "$HL_CODEX_CONFIG")"
  [ -f "$HL_CODEX_CONFIG" ] || : >"$HL_CODEX_CONFIG"
  new=$(hl_codex_config_apply "$HL_CODEX_CONFIG" "$HL_BASE" "$(hl_pick_model "$managed" "$HL_DEFAULT_MODEL" "$HL_MODELS")" "$HL_HELPER")
  printf '%s\n' "$new" | hl_write "$HL_CODEX_CONFIG"
  case $? in 0) hl_fix "provider homelab is the default (an earlier model/model_provider is kept, commented out)" ;; 1) hl_ok "up to date" ;; *) hl_fail "could not write" ;; esac
  hl_state_set codex managed
}

hl_step_agent() {
  local self dest
  hl_say "Sync agent ($HL_LABEL, every 5 min)"
  dest="$HL_SHARE/install-mac.sh"
  if [ "$HL_MODE" = check ]; then
    [ -f "$HL_PLIST" ] && hl_ok "LaunchAgent installed" || hl_warn "LaunchAgent not installed"
    launchctl print "gui/$(id -u)/$HL_LABEL" >/dev/null 2>&1 && hl_ok "loaded" || hl_warn "not loaded"
    [ -f "$HL_LOG" ] && hl_say "  last log line: $(tail -n 1 "$HL_LOG")"
    return
  fi
  self=${HL_SELF:-}
  if [ -n "$self" ] && [ -f "$self" ]; then
    hl_write "$dest" 755 <"$self"
  elif [ ! -f "$dest" ]; then
    hl_fail "can't copy this script for the agent (run it from a file, not a pipe)"; return
  fi
  hl_plist_render "$dest" "$HL_LOG" | hl_write "$HL_PLIST" 644
  [ "${HL_NO_LAUNCHCTL:-0}" = 1 ] && { hl_ok "written (launchctl skipped)"; return; }
  launchctl bootout "gui/$(id -u)/$HL_LABEL" 2>/dev/null
  if launchctl bootstrap "gui/$(id -u)" "$HL_PLIST" 2>/dev/null; then hl_ok "loaded"; else hl_warn "written but not loaded (log in to the Mac's desktop, then run again)"; fi
}

# --sync: what the LaunchAgent runs. Quiet, never asks, never touches a file that isn't ours or didn't change.
hl_sync() {
  local key list
  HL_LOCK="$HL_CONF/.sync.lock"
  mkdir -p "$HL_CONF"
  # One run at a time; a lock older than 10 minutes is from a run that died
  mkdir "$HL_LOCK" 2>/dev/null || { [ -n "$(find "$HL_LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ] && rmdir "$HL_LOCK" && mkdir "$HL_LOCK"; } \
    || { hl_log "another sync is running"; return 0; }
  trap 'rmdir "$HL_LOCK" 2>/dev/null' EXIT
  key=$(hl_any_key) || { hl_log "no key in the Keychain"; return 0; }
  list=$(hl_fetch_models "$key") || { hl_log "LiteLLM unreachable (HTTP ${HL_HTTP:-000}); nothing changed"; return 0; }
  key=""
  [ -n "$list" ] || { hl_log "LiteLLM listed no chat models; nothing changed"; return 0; }
  HL_MODELS=$list
  printf '%s\n' "$list" | hl_write "$HL_MODELS_CACHE" 644 && hl_log "models now: $(printf '%s' "$list" | tr '\n' ' ')"
  [ -f "$HL_ENV" ] && { HL_BASE=$(hl_env_value "$HL_ENV" ANTHROPIC_BASE_URL); hl_step_env; }
  if [ "$(hl_state_get claude)" = managed ] && [ -f "$HL_CLAUDE_SETTINGS" ]; then
    local cur; cur=$(cat "$HL_CLAUDE_SETTINGS")
    if jq -e . >/dev/null 2>&1 <<<"$cur" && [ "$(hl_claude_picker_owner "$cur")" != foreign ]; then
      hl_claude_settings_apply "$cur" "$(jq -r '.apiKeyHelper // empty' <<<"$cur")" "$list" "$HL_DEFAULT_MODEL" | jq . \
        | hl_write "$HL_CLAUDE_SETTINGS" && hl_log "Claude Code /model picker updated"
    fi
  fi
  if [ "$(hl_state_get cursor)" = managed ] && [ -f "$HL_CURSOR_SETTINGS" ]; then
    local cs; cs=$(cat "$HL_CURSOR_SETTINGS")
    jq -e . >/dev/null 2>&1 <<<"$cs" && hl_cursor_env_apply "$cs" "$HL_BASE" "$HL_CA" "$list" "$HL_DEFAULT_MODEL" | jq . \
      | hl_write "$HL_CURSOR_SETTINGS" && hl_log "Cursor's Claude Code extension: model names updated"
  fi
  if [ "$(hl_state_get codex)" = managed ]; then
    local m; m=$(hl_codex_managed_model "$HL_CODEX_CONFIG")
    if [ -n "$m" ] && ! hl_in_list "$m" "$list"; then
      hl_codex_config_apply "$HL_CODEX_CONFIG" "$(hl_codex_base)" "$(hl_pick_model "" "$HL_DEFAULT_MODEL" "$list")" "$HL_HELPER" \
        | hl_write "$HL_CODEX_CONFIG" && hl_log "Codex: $m is gone, default model reset"
    fi
  fi
  hl_prune_backups
  return 0
}

hl_codex_base() { sed -nE 's#^base_url = "(.*)/v1"$#\1#p' "$HL_CODEX_CONFIG" | tail -n 1; }

# Keep 30 days of backups, and always the oldest (the state before the first install)
hl_prune_backups() {
  local first
  [ -d "$HL_SHARE/backups" ] || return 0
  first=$(find "$HL_SHARE/backups" -mindepth 1 -maxdepth 1 -type d | sort | head -n 1)
  find "$HL_SHARE/backups" -mindepth 1 -maxdepth 1 -type d -mtime +30 | while IFS= read -r d; do
    [ "$d" = "$first" ] || rm -rf "$d"
  done
}

hl_uninstall() {
  local acct
  hl_say "Removing the homelab model setup (backups of every file are kept in $HL_SHARE/backups)"
  [ "${HL_NO_LAUNCHCTL:-0}" = 1 ] || launchctl bootout "gui/$(id -u)/$HL_LABEL" 2>/dev/null
  [ -f "$HL_PLIST" ] && hl_backup "$HL_PLIST" && rm -f "$HL_PLIST" && hl_fix "LaunchAgent removed"
  if [ -f "$HL_ZSHRC" ] && grep -qF "$HL_MARK_BEGIN" "$HL_ZSHRC"; then
    hl_zshrc_remove "$HL_ZSHRC" | hl_write "$HL_ZSHRC" && hl_fix "shell block removed"
  fi
  if [ -f "$HL_CLAUDE_SETTINGS" ] && jq -e . "$HL_CLAUDE_SETTINGS" >/dev/null 2>&1; then
    hl_claude_settings_remove "$(cat "$HL_CLAUDE_SETTINGS")" | jq . | hl_write "$HL_CLAUDE_SETTINGS" && hl_fix "Claude Code: apiKeyHelper and /model picker removed"
  fi
  if [ -n "$(hl_codex_managed_model "$HL_CODEX_CONFIG")" ]; then
    printf '%s\n' "$(hl_codex_config_remove "$HL_CODEX_CONFIG")" | hl_write "$HL_CODEX_CONFIG" && hl_fix "Codex: provider removed, earlier model settings restored"
  fi
  if [ "$(hl_state_get cursor)" = managed ]; then
    hl_say "  Cursor's Claude Code extension keeps https and the CA but has no key without apiKeyHelper:"
    hl_say "  restore $HL_CURSOR_SETTINGS from the oldest backup if you want the old setup back."
  fi
  [ -f "$HL_HELPER" ] && hl_backup "$HL_HELPER" && rm -f "$HL_HELPER" && hl_fix "Keychain helper removed"
  [ -f "$HL_ENV" ] && rm -f "$HL_ENV" "$HL_STATE" "$HL_MODELS_CACHE"
  for acct in claude-code cursor codex; do
    [ -n "$(hl_key_get "$acct")" ] || continue
    hl_confirm "  Delete the $acct key from the Keychain?" && hl_key_delete "$acct" && hl_fix "$acct key deleted"
  done
  hl_say "The web CA stays trusted (remove \"nghodki homelab web CA\" in Keychain Access if you want)."
}

hl_health() {
  local key list body out
  hl_say "Health check"
  key=$(hl_any_key) || { hl_fail "no key"; return; }
  list=$(hl_fetch_models "$key") && hl_ok "/v1/models: $(printf '%s' "$list" | tr '\n' ' ')" || hl_fail "/v1/models: HTTP $HL_HTTP"
  hl_say "  Chat through each tool with $HL_DEFAULT_MODEL. If the model is asleep, the first answer takes about 5 minutes."
  # Room for the model's reasoning before the answer; a reply that is all reasoning still proves the path works
  body=$(jq -nc --arg m "$HL_DEFAULT_MODEL" '{model: $m, max_tokens: 400, messages: [{role: "user", content: "Reply with the single word: pong"}]}')
  out=$(printf 'header = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\n' "$key" \
    | curl -sS -m 600 -K - -d "$body" "$HL_BASE/v1/chat/completions" 2>/dev/null \
    | jq -r '.choices[0].message | if (.content // "") != "" then .content elif (.reasoning_content // "") != "" then "(answered; reasoning only)" else empty end // empty' 2>/dev/null)
  key=""
  [ -n "$out" ] && hl_ok "LiteLLM chat: $(printf '%s' "$out" | head -c 60 | tr '\n' ' ')" || hl_fail "LiteLLM chat: no answer"
  if hl_want claude && command -v claude >/dev/null 2>&1; then
    # shellcheck source=/dev/null
    out=$(cd "$HOME" && (. "$HL_ENV" && hl_timeout 600 claude -p --model "$HL_DEFAULT_MODEL" "Reply with the single word: pong") 2>&1 </dev/null | tail -n 1)
    case "$out" in *[Pp]ong*) hl_ok "claude -p: $out" ;; *) hl_fail "claude -p: $(printf '%s' "$out" | head -c 200)" ;; esac
  fi
  if hl_want codex && command -v codex >/dev/null 2>&1; then
    # shellcheck source=/dev/null
    out=$(cd "$HOME" && (. "$HL_ENV" && hl_timeout 600 codex exec --skip-git-repo-check "Reply with the single word: pong") 2>/dev/null </dev/null | tail -n 1)
    case "$out" in *[Pp]ong*) hl_ok "codex exec: $out" ;; *) hl_fail "codex exec: no answer (run: codex exec 'hi')" ;; esac
  fi
  if hl_want cursor; then
    hl_say "  Cursor: open the Claude Code panel and run /model (no command-line test for the extension)."
  fi
}

hl_usage() { sed -n '2,13p' "${HL_SELF:-$0}" 2>/dev/null | sed 's/^# \{0,1\}//'; }

hl_main() {
  HL_MODE=install; HL_TOOLS=""; HL_YES=0
  HL_BASE=$HL_BASE_URL_DEFAULT; HL_DEFAULT_MODEL=$HL_DEFAULT_MODEL_DEFAULT
  while [ $# -gt 0 ]; do
    case "$1" in
      --claude) HL_TOOLS="$HL_TOOLS claude" ;;
      --cursor) HL_TOOLS="$HL_TOOLS cursor" ;;
      --codex) HL_TOOLS="$HL_TOOLS codex" ;;
      --check) HL_MODE=check ;;
      --repair) HL_MODE=repair ;;
      --uninstall) HL_MODE=uninstall ;;
      --sync) HL_MODE=sync ;;
      --yes|-y) HL_YES=1 ;;
      --base-url) HL_BASE=${2:?--base-url needs a URL}; shift ;;
      --default-model) HL_DEFAULT_MODEL=${2:?--default-model needs a name}; shift ;;
      -h|--help) hl_usage; return 0 ;;
      *) hl_die "unknown option $1 (see --help)" ;;
    esac
    shift
  done
  HL_BASE=${HL_BASE%/}; HL_BASE=${HL_BASE%/v1}
  [ "$(uname -s)" = Darwin ] || [ -n "${HL_TEST_KEYDIR:-}" ] || hl_die "this is for macOS"
  command -v jq >/dev/null 2>&1 || hl_die "jq not found (macOS 15+ has /usr/bin/jq; older: brew install jq)"
  hl_init_paths
  umask 022
  if [ "$HL_MODE" = sync ]; then
    HL_DEFAULT_MODEL=$(hl_state_get default_model); HL_DEFAULT_MODEL=${HL_DEFAULT_MODEL:-$HL_DEFAULT_MODEL_DEFAULT}
    hl_sync; return 0
  fi
  [ "$HL_MODE" = uninstall ] && { hl_uninstall; return 0; }
  HL_TOOLS=${HL_TOOLS# }
  [ -n "$HL_TOOLS" ] || HL_TOOLS=$(hl_detect_tools)
  [ -n "$HL_TOOLS" ] || hl_die "none of Claude Code, Cursor or Codex found; pick with --claude/--cursor/--codex"
  hl_say "homelab models (install-mac.sh v$HL_VERSION): $HL_MODE for: $HL_TOOLS"
  if [ "$HL_MODE" != check ]; then
    mkdir -p "$HL_CONF" "$HL_SHARE"; chmod 700 "$HL_CONF" "$HL_SHARE"
    local f
    for f in "$HL_ZSHRC" "$HL_CLAUDE_SETTINGS" "$HL_CODEX_CONFIG" "$HL_CURSOR_SETTINGS"; do hl_backup "$f"; done
    [ -n "$HL_BACKUP_DIR" ] && hl_say "Backup of the current files: $HL_BACKUP_DIR"
    hl_state_set default_model "$HL_DEFAULT_MODEL"
  fi
  hl_step_hosts
  hl_step_reach || [ "$HL_MODE" = check ] || hl_die "fix the connection first (Tailscale on? see the page's troubleshooting)"
  hl_step_ca
  hl_step_keys
  hl_step_helper
  hl_step_models
  { hl_want claude || hl_want codex || hl_want cursor; } && hl_step_shell
  # The extension in Cursor is Claude Code too: it needs the apiKeyHelper once its key leaves Cursor's settings
  { hl_want claude || hl_want cursor; } && hl_step_claude
  hl_want cursor && hl_step_cursor
  hl_want codex && hl_step_codex
  hl_step_agent
  if [ "$HL_MODE" = check ]; then
    hl_say ""; [ "$HL_PROBLEMS" -eq 0 ] && hl_say "All good." || hl_say "$HL_PROBLEMS thing(s) to fix: run install-mac.sh --repair"
    [ "$HL_PROBLEMS" -eq 0 ]; return
  fi
  hl_say ""
  hl_health
  hl_say ""
  hl_say "Done. Open a new terminal (or: . \"$HL_ENV\"), then run claude and /model."
}

# Sourced by the tests with HL_SOURCE_ONLY=1: functions only
if [ "${HL_SOURCE_ONLY:-0}" != 1 ]; then
  case "${BASH_SOURCE[0]:-}" in */*|*.sh) HL_SELF=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/$(basename "${BASH_SOURCE[0]}") ;; *) HL_SELF="" ;; esac
  hl_main "$@"
fi
