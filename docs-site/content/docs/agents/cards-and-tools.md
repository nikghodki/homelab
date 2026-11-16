---
title: Agent cards and MCP tools
description: A2A agent-card scanning, Agentic Radar, and MCP tool pinning with reviewed hashes and accepted findings.
---

## Agent cards (P4.9)

- Each agent's A2A card is `agents/<name>/card.yaml`. CI converts it to JSON and runs `a2a-scanner scan-card` with the
  offline analyzers `yara`, `heuristic`, `spec` (no endpoint analyzer: CI calls no agents). HIGH or CRITICAL fails CI.
- `scan-agents.py --self-test` first scans `.github/scripts/fixtures/unsafe-agent-card.json` and fails if the scanner
  no longer flags it, so a broken scanner can't pass silently.
- One card today: `agents/hermes/card.yaml`.

## Agentic Radar

Agents written in a framework Radar understands (LangGraph, CrewAI, n8n, OpenAI Agents, AutoGen) opt in with
`agents/<name>/radar.yaml` (`{framework, path}`). Radar maps tools and risks into an HTML report (CI artifact
`agentic-radar`); it never fails the build. No agent opts in yet. Radar has its own venv because it pins `rich<14`.

## MCP tools (P4.3)

One folder per approved MCP server:

```
tools/<server>/
  server.yaml    transport, host, which agents use which tools, how to re-export, reviewed scanner findings
  tools.json     the server's tools/list output, as approved
  tools.sha256   sha256 of each tool definition (canonical JSON of the whole tool object)
```

| Server | Host | Transport | Tools | Used by |
|---|---|---|---|---|
| `picoclaw_only` | Jetson | stdio (Node, `picoclaw-hardware-mcp.js`) | 20 | `hermes-nikhil`, includes `send_to_picoclaw_agent`, `check_picoclaw_agent_connection` |
| `homeassistant` | Jetson | streamable HTTP, `http://localhost:8123/api/mcp/assist`, HA token | 24 | `hermes-nikhil`, all |

CI (`ai-scanners` job):

1. `mcp-tool-hashes.py check tools` fails if a tool was added, removed or changed without `tools.sha256` being updated
   in the same PR, and (since #74) if a pinned server's `tools.json` is missing. A changed description or schema (tool
   poisoning, a "rug pull") must show up in a reviewed diff.
2. `scan-mcp-tools.py tools` runs mcp-scanner (YARA, offline) on every `tools.json` and fails on HIGH/CRITICAL. A
   reviewed false positive goes under `accepted_findings` in `server.yaml`, pinned to the tool's sha256, so it lapses as
   soon as the tool changes.

Accepted today: `send_to_picoclaw_agent`, `yara_analyzer`, "DATA EXFILTRATION": sending a message to another agent is
the tool's purpose, over the fleet's own TLS broker (reviewed 2026-11-15).

The include list in Hermes's config is a client-side filter; the server still offers every tool, so every tool is
pinned.

## Re-export a server

On the host that runs it (stdlib Python, nothing to install; copy the script there):

```bash
python3 export-mcp-tools.py --stdio -- <command> [args...] > tools.json
HA_TOKEN=... python3 export-mcp-tools.py --url <url> --token-env HA_TOKEN > tools.json
```

The exact command per server is in its `server.yaml` (for `picoclaw_only`, with
`MQTT_CREDS_FILE=/nonexistent MQTT_BROKER=mqtt://127.0.0.1:1` so no credentials are read). Copy the file into `tools/<server>/`, read the diff, run
`.github/scripts/mcp-tool-hashes.py update`, commit both files together. Re-export Home Assistant after exposing or
renaming entities (the tool enums depend on them).

## Admission and the nightly drift check (P4.3)

A new server needs a folder in `tools/` **and** an entry in `policies/defenseclaw/mcp-servers.yaml` with the same
launch. On the Jetson, DefenseClaw refuses `defenseclaw mcp set` for anything else, and the `mcp-drift` timer (role
`mcp_drift`, ~03:40,
both accounts) compares each live approved server's `tools/list` with `tools.sha256` every night and flags unapproved
servers in Hermes' config. CI also checks that the registry launch matches `server.yaml` (`policies/defenseclaw/tests`)
and runs the drift script's tests. Details: [DefenseClaw](../security/defenseclaw.md), runbooks/mcp-admission.md.

When it reports drift: treat a changed, added or removed tool as possible tool poisoning until reviewed. Compare a fresh
export with `tools.json`; if expected (an HA entity exposed or renamed, a roboclaw update), commit the new export and
hashes in a PR and re-run `playbooks/defenseclaw.yml --limit jetson`; if not, remove the server from Hermes and
investigate.

## Not done yet

- The `wedding`, `vision-ai` and `home-board` servers were removed from both Hermes profiles on 2026-11-15, so they are
  not exported.
- Registering servers in LiteLLM's MCP gateway with per-key tool permissions (P4.2). LiteLLM doesn't detect
  tool-description changes, which is why the drift check exists (D20).
