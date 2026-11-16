#!/usr/bin/env bash
# What a pr-checks run covers. Writes to $GITHUB_OUTPUT:
#   code=true|false  false only for a PR that changes nothing but docs (then lint, tests and scans are skipped)
#   yaml=true|false  the PR changes a *.yml/*.yaml file (a docs-only PR still gets yamllint then)
#   base, head       the PR's own commits for the secret scanners (base..head); empty outside a PR (full history)
#   day              the cache day for the Trivy DB and Ansible collections (refreshed by the daily run)
# A PR run checks out the merge commit refs/pull/N/merge: HEAD^1 is main, HEAD^2 the PR head (fetch-depth >= 2).
# Docs: docs/, docs-site/, runbooks/, decisions/ and *.md, except under agents/ and tools/ (SKILL.md is scanned).
set -euo pipefail
out=${GITHUB_OUTPUT:-/dev/stdout}
# A PR uses the cache day of the last daily run (08:47 UTC; 10 h leaves room for its delay), so it restores that
# run's caches instead of saving its own copy before the daily run has made today's
if [ "${GITHUB_EVENT_NAME:-}" = pull_request ]; then day=$(date -u -d '-10 hours' +%Y-%m-%d); else day=$(date -u +%Y-%m-%d); fi
echo "day=$day" >> "$out"

if [ "${GITHUB_EVENT_NAME:-}" != pull_request ]; then
  echo "event ${GITHUB_EVENT_NAME:-none}: full suite, secret scanners on the full history of $(git rev-parse HEAD)"
  printf 'code=true\nyaml=true\nbase=\nhead=\n' >> "$out"
  exit 0
fi

base=$(git rev-parse HEAD^1)
head=$(git rev-parse HEAD^2)
if [ -n "${PR_HEAD_SHA:-}" ] && [ "$head" != "$PR_HEAD_SHA" ]; then
  echo "::error::merge commit's second parent $head is not the PR head $PR_HEAD_SHA"; exit 1
fi
n=$(git rev-list --count "$base..$head")
if [ "$n" -eq 0 ]; then echo "::error::no PR commits in $base..$head"; exit 1; fi

files=$(git diff --name-only --no-renames "$base" HEAD)
echo "PR commits $base..$head ($n); files changed against main:"
echo "${files:-  (none)}" | sed 's/^/  /'

code=false; yaml=false
while IFS= read -r f; do
  [ -n "$f" ] || continue
  case "$f" in
    *.yml|*.yaml) yaml=true ;;
  esac
  case "$f" in
    agents/*|tools/*) code=true ;;
    docs/*|docs-site/*|runbooks/*|decisions/*|*.md) ;;
    *) code=true ;;
  esac
done <<< "$files"
# an empty diff (e.g. a revert of a revert) gets the full suite
[ -n "$files" ] || code=true

echo "code=$code yaml=$yaml"
printf 'code=%s\nyaml=%s\nbase=%s\nhead=%s\n' "$code" "$yaml" "$base" "$head" >> "$out"
