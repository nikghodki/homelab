#!/usr/bin/env bash
# shellcheck over every shell script in the repo: tracked *.sh files, and *.j2 templates whose first line is a
# sh/bash shebang (rendered for the check by stripping Jinja: {{ expr }} becomes a plain word, {% %} and {# #} tags
# are dropped). Warnings and errors fail; info and style notes are printed but don't (--severity=warning).
# Usage: shellcheck.sh <shellcheck image pinned by digest>
set -euo pipefail

image=${1:?usage: shellcheck.sh <image@sha256:...>}
case "$image" in *@sha256:*) ;; *) echo "shellcheck image must be pinned by digest: $image" >&2; exit 2 ;; esac

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

files=()
while IFS= read -r f; do
  files+=("$f")
done < <(git ls-files '*.sh')

while IFS= read -r f; do
  head -n 1 "$f" | grep -qE '^#!.*[/ ](ba|da)?sh( |$)' || continue
  mkdir -p "$work/$(dirname "$f")"
  sed -E -e 's/\{%[^%]*%\}//g' -e 's/\{#[^#]*#\}//g' -e 's/\{\{[^}]*\}\}/JINJA/g' "$f" > "$work/$f"
  files+=("/rendered/$f")
done < <(git ls-files '*.j2')

echo "shellcheck: ${#files[@]} files"
docker run --rm -v "$PWD:/repo:ro" -v "$work:/rendered:ro" -w /repo "$image" \
  --external-sources --source-path=SCRIPTDIR --severity=warning --format=gcc "${files[@]}"
