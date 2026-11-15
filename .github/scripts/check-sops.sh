#!/usr/bin/env bash
# Fail if any file under secrets/ is not SOPS-encrypted. Plain README/.gitkeep files are allowed.
set -euo pipefail
bad=0
while IFS= read -r -d '' f; do
  case "$(basename "$f")" in README.md|.gitkeep) continue ;; esac
  if ! grep -q 'ENC\[' "$f" || ! grep -Eq '(^|")sops("|:)' "$f"; then
    echo "::error file=$f::not SOPS-encrypted"
    bad=1
  fi
done < <(find secrets -type f -print0 2>/dev/null)
[ "$bad" -eq 0 ] && echo "secrets/: all files are SOPS-encrypted (or none exist)"
exit "$bad"
