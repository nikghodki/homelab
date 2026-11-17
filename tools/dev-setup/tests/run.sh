#!/usr/bin/env bash
# Tests for the pure logic of install-mac.sh (config rewriting, model filtering, /etc/hosts pins). No network, no
# Keychain, no macOS needed: CI runs it on Linux (pr-checks "Unit tests: Mac dev-setup"). Needs bash, jq, awk, python3.
# Usage: bash tools/dev-setup/tests/run.sh
set -u -o pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fx="$here/fixtures"
export HL_SOURCE_ONLY=1
# shellcheck source=../install-mac.sh
. "$here/../install-mac.sh"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export HOME="$work/home"; mkdir -p "$HOME"
hl_init_paths

pass=0; failed=0
check() { # name, command...
  local name=$1; shift
  if "$@"; then pass=$((pass + 1)); else failed=$((failed + 1)); printf 'FAIL: %s\n' "$name"; fi
}
eq() { [ "$1" = "$2" ] || { printf '  expected: %s\n  got:      %s\n' "$2" "$1"; return 1; }; }
json_eq() { eq "$(jq -cS . <<<"$1")" "$(jq -cS . <<<"$2")"; }
not() { ! "$@"; }
write_two() { printf 'two\n' | hl_write "$1"; }
write_unchanged() { printf 'two\n' | hl_write "$1"; [ $? -eq 1 ]; }
toml_ok() { "${PYTHON:-python3}" -c 'import sys, tomllib; tomllib.loads(sys.stdin.read())' <<<"$1"; }

# --- model list
models=$(cat "$fx/v1-models.json"); info=$(cat "$fx/model-info.json")
check "filter: chat models only, sorted, no wildcard, no duplicates" \
  eq "$(hl_filter_models "$models" "$info" | tr '\n' ' ')" "flint-nvfp4 qwen3.8-27b qwen3.8-27b-nothink twil-8b "
check "filter: without /model/info every listed name counts" \
  eq "$(hl_filter_models "$models" "" | tr '\n' ' ')" "bge-m3 flint-nvfp4 qwen3.8-27b qwen3.8-27b-nothink twil-8b whisper-large-v3-turbo "
check "filter: empty list" eq "$(hl_filter_models '{"data":[]}' '')" ""
list=$(printf 'flint-nvfp4\nqwen3.8-27b\ntwil-8b')
check "pick: kept when served" eq "$(hl_pick_model flint-nvfp4 qwen3.8-27b "$list")" flint-nvfp4
check "pick: gone, falls back to the default" eq "$(hl_pick_model qwen3.6-35b qwen3.8-27b "$list")" qwen3.8-27b
check "pick: default gone too, first served" eq "$(hl_pick_model "" gone "$list")" flint-nvfp4

# --- /etc/hosts
check "hosts: finds uncommented pins only" eq "$(hl_hosts_pins "$fx/hosts" | cut -d: -f1 | tr '\n' ' ')" "4 5 "
check "hosts: unpin comments out exactly those" \
  eq "$(hl_hosts_unpin "$fx/hosts" | grep -c '^# disabled by homelab install-mac.sh: ')" 2
check "hosts: unpinned file has no pins" eq "$(hl_hosts_unpin "$fx/hosts" >"$work/h"; hl_hosts_pins "$work/h")" ""

# --- Claude Code settings.json (the Air's odd claudeCode.* keys must survive)
orig=$(cat "$fx/claude-settings.json")
new=$(hl_claude_settings_apply "$orig" "/h/.local/bin/homelab-model-key claude-code" "$list" qwen3.8-27b)
check "claude: helper set" eq "$(jq -r .apiKeyHelper <<<"$new")" "/h/.local/bin/homelab-model-key claude-code"
check "claude: picker rows, default first" eq "$(jq -r '[.modelPicker.options[].model] | join(" ")' <<<"$new")" "qwen3.8-27b flint-nvfp4 twil-8b"
check "claude: picker replaces the built-in rows" eq "$(jq -r .modelPicker.replaceBuiltInOptions <<<"$new")" true
check "claude: other keys untouched" json_eq "$(jq 'del(.apiKeyHelper, .modelPicker)' <<<"$new")" "$orig"
check "claude: picker is ours" eq "$(hl_claude_picker_owner "$new")" ours
check "claude: no picker" eq "$(hl_claude_picker_owner "$orig")" none
check "claude: someone else's picker" eq "$(hl_claude_picker_owner '{"modelPicker":{"options":[{"model":"x"}]}}')" foreign
check "claude: idempotent" json_eq "$(hl_claude_settings_apply "$new" "/h/.local/bin/homelab-model-key claude-code" "$list" qwen3.8-27b)" "$new"
check "claude: remove gives the original back" json_eq "$(hl_claude_settings_remove "$new")" "$orig"
check "claude: remove keeps a foreign helper" eq "$(hl_claude_settings_remove '{"apiKeyHelper":"vault get"}' | jq -r .apiKeyHelper)" "vault get"
check "claude: empty settings" eq "$(hl_claude_settings_apply "" h "$list" qwen3.8-27b | jq -r '.modelPicker.options | length')" 3

# --- Cursor settings.json (Claude Code extension env)
cur=$(cat "$fx/cursor-settings.json")
check "cursor: issues found" eq "$(hl_cursor_env_issues "$cur" https://model.nghodki.ai)" "key-in-file base-url no-ca"
cnew=$(hl_cursor_env_apply "$cur" https://model.nghodki.ai /h/ca.crt "$list" qwen3.8-27b)
env_of() { jq -r --arg n "$2" '.["claudeCode.environmentVariables"][] | select(.name == $n) | .value' <<<"$1"; }
check "cursor: no key left in the file" eq "$(env_of "$cnew" ANTHROPIC_API_KEY)$(env_of "$cnew" ANTHROPIC_AUTH_TOKEN)" ""
check "cursor: https base URL" eq "$(env_of "$cnew" ANTHROPIC_BASE_URL)" https://model.nghodki.ai
check "cursor: CA" eq "$(env_of "$cnew" NODE_EXTRA_CA_CERTS)" /h/ca.crt
check "cursor: a served model is kept" eq "$(env_of "$cnew" ANTHROPIC_DEFAULT_HAIKU_MODEL)" flint-nvfp4
check "cursor: a gone model is replaced" eq "$(env_of "$cnew" ANTHROPIC_DEFAULT_OPUS_MODEL)" qwen3.8-27b
check "cursor: other variables kept" eq "$(env_of "$cnew" DISABLE_TELEMETRY)" 1
check "cursor: other settings kept" json_eq "$(jq 'del(.["claudeCode.environmentVariables"])' <<<"$cnew")" "$(jq 'del(.["claudeCode.environmentVariables"])' <<<"$cur")"
check "cursor: clean after" eq "$(hl_cursor_env_issues "$cnew" https://model.nghodki.ai)" ""
check "cursor: idempotent" json_eq "$(hl_cursor_env_apply "$cnew" https://model.nghodki.ai /h/ca.crt "$list" qwen3.8-27b)" "$cnew"
bed='{"claudeCode.environmentVariables":[{"name":"CLAUDE_CODE_USE_BEDROCK","value":"1"},{"name":"ANTHROPIC_MODEL","value":"global.anthropic.claude-opus-5-5"}]}'
check "cursor: Bedrock setup untouched" json_eq "$(hl_cursor_env_apply "$bed" https://model.nghodki.ai /h/ca.crt "$list" qwen3.8-27b force)" "$bed"
check "cursor: Bedrock detected" eq "$(hl_cursor_env_issues "$bed" https://model.nghodki.ai)" bedrock
check "cursor: no gateway, not forced: untouched" json_eq "$(hl_cursor_env_apply '{"a":1}' https://m /c "$list" qwen3.8-27b)" '{"a":1}'
check "cursor: no gateway, forced: configured" eq "$(hl_cursor_env_apply '{"a":1}' https://m /c "$list" qwen3.8-27b force | jq -r '[.["claudeCode.environmentVariables"][].name] | join(" ")')" \
  "ANTHROPIC_BASE_URL NODE_EXTRA_CA_CERTS ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL"

# --- Codex config.toml
cp "$fx/codex-config.toml" "$work/c.toml"
c1=$(hl_codex_config_apply "$work/c.toml" https://model.nghodki.ai qwen3.8-27b /h/.local/bin/homelab-model-key)
check "codex: valid TOML" toml_ok "$c1"
toml_get() { "${PYTHON:-python3}" -c 'import sys, tomllib; d = tomllib.loads(sys.stdin.read()); print(eval(sys.argv[1]))' "$1" <<<"$2"; }
check "codex: provider is the default" eq "$(toml_get 'd["model_provider"], d["model"]' "$c1")" "('homelab', 'qwen3.8-27b')"
check "codex: provider table" eq "$(toml_get 'd["model_providers"]["homelab"]["base_url"], d["model_providers"]["homelab"]["auth"]["args"]' "$c1")" \
  "('https://model.nghodki.ai/v1', ['codex'])"
check "codex: other provider kept" eq "$(toml_get 'd["model_providers"]["openrouter"]["env_key"]' "$c1")" OPENROUTER_API_KEY
check "codex: other top-level keys kept" eq "$(toml_get 'd["model_reasoning_effort"]' "$c1")" high
check "codex: managed model" eq "$(printf '%s\n' "$c1" >"$work/c1.toml"; hl_codex_managed_model "$work/c1.toml")" qwen3.8-27b
check "codex: idempotent" eq "$(hl_codex_config_apply "$work/c1.toml" https://model.nghodki.ai qwen3.8-27b /h/.local/bin/homelab-model-key)" "$c1"
check "codex: remove restores the original" eq "$(hl_codex_config_remove "$work/c1.toml")" "$(hl_squeeze_blank_tail <"$fx/codex-config.toml")"
check "codex: our provider isn't foreign" not hl_codex_foreign_provider "$work/c1.toml"
printf '[model_providers.homelab]\nbase_url = "x"\n' >"$work/f.toml"
check "codex: someone else's homelab provider" hl_codex_foreign_provider "$work/f.toml"
: >"$work/empty.toml"
check "codex: from an empty file" toml_ok "$(hl_codex_config_apply "$work/empty.toml" https://m qwen3.8-27b /h/k)"
check "codex: model switch" eq "$(printf '%s\n' "$(hl_codex_config_apply "$work/c1.toml" https://m flint-nvfp4 /h/k)" >"$work/c2.toml"; hl_codex_managed_model "$work/c2.toml")" flint-nvfp4

# --- ~/.zshrc
z1=$(hl_zshrc_apply "$fx/zshrc" /h/.config/homelab-models/env.sh)
check "zshrc: old exports gone" eq "$(grep -c '^export ANTHROPIC_' <<<"$z1")" 0
check "zshrc: commented lines kept" eq "$(grep -c '^# export AWS_BEARER_TOKEN_BEDROCK=' <<<"$z1")" 1
check "zshrc: other exports kept" eq "$(grep -c 'export OTHER_TOKEN=keep-me' <<<"$z1")" 1
check "zshrc: one block" eq "$(grep -cF "$HL_MARK_BEGIN" <<<"$z1")" 1
check "zshrc: block sources env.sh" eq "$(grep -c '^\[ -r "/h/.config/homelab-models/env.sh" \] && \. ' <<<"$z1")" 1
printf '%s\n' "$z1" >"$work/z1"
check "zshrc: idempotent" eq "$(hl_zshrc_apply "$work/z1" /h/.config/homelab-models/env.sh)" "$z1"
check "zshrc: remove drops only the block" eq "$(hl_zshrc_remove "$work/z1" | grep -cF 'homelab')" 0
check "zshrc: legacy names" eq "$(hl_zshrc_legacy_names "$fx/zshrc" | tr '\n' ' ')" \
  "ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL ANTHROPIC_CUSTOM_MODEL_OPTION "
check "zshrc: no legacy names after" eq "$(hl_zshrc_legacy_names "$work/z1")" ""
check "zshrc: model value read" eq "$(hl_zshrc_model_value "$fx/zshrc" ANTHROPIC_DEFAULT_HAIKU_MODEL)" flint-nvfp4

# --- env.sh, LaunchAgent, helper
hl_env_render https://model.nghodki.ai /h/ca.crt /h/b.pem qwen3.8-27b qwen3.8-27b flint-nvfp4 >"$work/env.sh"
check "env: values read back" eq "$(hl_env_value "$work/env.sh" ANTHROPIC_DEFAULT_HAIKU_MODEL) $(hl_env_value "$work/env.sh" ANTHROPIC_BASE_URL)" "flint-nvfp4 https://model.nghodki.ai"
check "env: POSIX sh" sh -n "$work/env.sh"
check "env: no key" not grep -qE "sk-|KEY=|TOKEN=" "$work/env.sh"
check "plist: parses" "${PYTHON:-python3}" -c 'import plistlib, sys; d = plistlib.loads(sys.stdin.buffer.read()); assert d["StartInterval"] == 300 and d["ProgramArguments"][-1] == "--sync"' \
  < <(hl_plist_render /h/s.sh /h/l.log)
check "helper: POSIX sh" sh -n <(hl_helper_render)

# --- atomic write with backup
printf 'one\n' >"$work/w"; chmod 600 "$work/w"
check "write: changed" write_two "$work/w"
check "write: mode kept" eq "$(stat -c '%a' "$work/w" 2>/dev/null || stat -f '%Lp' "$work/w")" 600
check "write: unchanged returns 1" write_unchanged "$work/w"
check "write: backup kept" eq "$(cat "$HL_SHARE"/backups/*/* 2>/dev/null | head -n 1)" one

# --- the sync agent, with LiteLLM stubbed: the picker follows the list, a gone Codex model is reset
hl_get() { case "$1" in /v1/models) cat "$fx/v1-models.json" ;; /v1/model/info) cat "$fx/model-info.json" ;; esac; }
export HL_TEST_KEYDIR="$work/keys"
hl_key_put claude-code test-key
export HL_DEFAULT_MODEL=qwen3.8-27b
mkdir -p "$HOME/.claude" "$HOME/.codex"
hl_claude_settings_apply "$orig" "/h/homelab-model-key claude-code" qwen3.8-27b qwen3.8-27b >"$HL_CLAUDE_SETTINGS"
hl_codex_config_apply "$fx/codex-config.toml" https://model.nghodki.ai qwen3.6-35b /h/k >"$HL_CODEX_CONFIG"
hl_state_set claude managed; hl_state_set codex managed
(hl_sync) >/dev/null
check "sync: picker follows LiteLLM" eq "$(jq -r '[.modelPicker.options[].model] | join(" ")' "$HL_CLAUDE_SETTINGS")" "qwen3.8-27b flint-nvfp4 qwen3.8-27b-nothink twil-8b"
check "sync: helper kept" eq "$(jq -r .apiKeyHelper "$HL_CLAUDE_SETTINGS")" "/h/homelab-model-key claude-code"
check "sync: gone Codex model reset" eq "$(hl_codex_managed_model "$HL_CODEX_CONFIG")" qwen3.8-27b
check "sync: Codex base URL kept" eq "$(hl_codex_base)" https://model.nghodki.ai
check "sync: model cache" eq "$(tr '\n' ' ' <"$HL_MODELS_CACHE")" "flint-nvfp4 qwen3.8-27b qwen3.8-27b-nothink twil-8b "
check "sync: lock released" not test -d "$HL_CONF/.sync.lock"
before=$(cat "$HL_CLAUDE_SETTINGS")
(hl_sync) >/dev/null
check "sync: nothing to do the second time" eq "$(cat "$HL_CLAUDE_SETTINGS")" "$before"
hl_get() { return 1; }
(hl_sync) >/dev/null
check "sync: LiteLLM down changes nothing" eq "$(cat "$HL_CLAUDE_SETTINGS")" "$before"

# --- the docs page shows the installer's SHA-256 (download, compare, run)
page="$here/../../../docs-site/content/docs/agents/coding-tools.md"
sha=$( (sha256sum "$here/../install-mac.sh" 2>/dev/null || shasum -a 256 "$here/../install-mac.sh") | cut -d' ' -f1)
check "page: shows the installer's sha256 ($sha)" grep -qF "# must print: $sha  install-mac.sh" "$page"

printf '\n%d passed, %d failed\n' "$pass" "$failed"
[ "$failed" -eq 0 ]
