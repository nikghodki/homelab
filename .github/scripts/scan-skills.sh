#!/usr/bin/env bash
# Scan every agent skill (a folder with SKILL.md) under agents/ and tools/ with the Cisco AI skill-scanner.
set -euo pipefail
mapfile -t skills < <(find agents tools -name SKILL.md -printf '%h\n' 2>/dev/null | sort -u)
if [ "${#skills[@]}" -eq 0 ]; then echo "no skills yet"; exit 0; fi
rc=0
for s in "${skills[@]}"; do
  echo "== $s"
  skill-scanner scan "$s" --policy strict --fail-on-severity high --format summary || rc=1
done
exit "$rc"
