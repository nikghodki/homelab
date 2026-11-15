#!/usr/bin/env bash
# Agentic Radar over agent code written in a framework it understands (plan P4.9).
# An agent opts in with agents/<name>/radar.yaml:  {framework: langgraph|crewai|n8n|openai-agents|autogen, path: src}
# The HTML reports are uploaded as a CI artifact; Radar maps tools and risks, it doesn't fail the build.
set -euo pipefail
mkdir -p reports/agentic-radar
found=0
for cfg in agents/*/radar.yaml; do
  [ -e "$cfg" ] || continue
  found=1
  dir=$(dirname "$cfg"); name=$(basename "$dir")
  fw=$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["framework"])' "$cfg")
  src=$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1])).get("path","."))' "$cfg")
  echo "Agentic Radar: $name ($fw, $dir/$src)"
  agentic-radar scan "$fw" -i "$dir/$src" -o "reports/agentic-radar/$name.html"
done
[ "$found" = 1 ] || echo "no agent code opts in (agents/*/radar.yaml); Hermes and picoclaw use frameworks Radar doesn't cover"
