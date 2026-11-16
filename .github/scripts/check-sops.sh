#!/usr/bin/env bash
# Fail if any file under secrets/ is not SOPS-encrypted (plain README/.gitkeep files are allowed), if any
# cluster/**/*.enc.yaml is not encrypted, or if cluster/ has a Secret manifest outside an *.enc.yaml file.
set -euo pipefail
bad=0
encrypted() { grep -q 'ENC\[' "$1" && grep -Eq '(^|")sops("|:)' "$1"; }
while IFS= read -r -d '' f; do
  case "$(basename "$f")" in README.md|.gitkeep) continue ;; esac
  if ! encrypted "$f"; then echo "::error file=$f::not SOPS-encrypted"; bad=1; fi
done < <(find secrets -type f -print0 2>/dev/null)
while IFS= read -r -d '' f; do
  case "$f" in
    *.enc.yaml|*.enc.yml)
      if ! encrypted "$f"; then echo "::error file=$f::not SOPS-encrypted"; bad=1; fi ;;
    *)
      if grep -Eq '^kind:[[:space:]]*Secret[[:space:]]*$' "$f"; then
        echo "::error file=$f::Secret manifest in cluster/ must be a SOPS-encrypted *.enc.yaml (KSOPS)"; bad=1
      fi ;;
  esac
done < <(find cluster -type f \( -name '*.yaml' -o -name '*.yml' \) -print0 2>/dev/null)
[ "$bad" -eq 0 ] && echo "secrets/ and cluster/: all secret files are SOPS-encrypted"
exit "$bad"
