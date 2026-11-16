# tools

Approved MCP servers, one folder each (plan P4.3):

```
tools/<server>/
  server.yaml    # transport, host, which agents use which tools, how to re-export, reviewed scanner findings
  tools.json     # output of the server's tools/list, as approved
  tools.sha256   # sha256 of each approved tool definition (description, inputSchema, everything)
```

| Server | Host | Transport | Tools |
|---|---|---|---|
| `picoclaw_only` | jetson | stdio (Node) | 20 (Hermes includes 2) |
| `homeassistant` | jetson | streamable HTTP, HA token | 24 |

CI (`pr-checks.yml` job `scans`):

- `.github/scripts/mcp-tool-hashes.py check` fails if any tool in a `tools.json` was added, removed or changed
  without `tools.sha256` being updated in the same PR. The hash file is the review record: a changed description
  or schema (tool poisoning, a "rug pull") has to show up as a diff in a reviewed PR.
- `.github/scripts/scan-mcp-tools.py tools` runs the Cisco AI Defense mcp-scanner (static, YARA) on every
  `tools.json` and fails on HIGH/CRITICAL. A reviewed false positive can be listed under `accepted_findings` in
  `server.yaml`; it is pinned to the tool's sha256, so it lapses as soon as the tool changes.

## Re-exporting a server

On the host that runs it (stdlib Python, nothing to install):

```bash
python3 export-mcp-tools.py --stdio -- <command> [args...] > tools.json     # stdio servers
HA_TOKEN=... python3 export-mcp-tools.py --url <url> --token-env HA_TOKEN > tools.json   # HTTP servers
```

The exact command for each server is in its `server.yaml`. Copy the file into `tools/<server>/`, read the diff,
then run `.github/scripts/mcp-tool-hashes.py update` and commit both files together.

## Admission and the nightly drift check

Only servers listed in `policies/defenseclaw/mcp-servers.yaml` (same launch as their `server.yaml`) are admitted by
DefenseClaw on the Jetson (`asset_policy.mcp.registry`, `registry_required`, mode `action`). Every night the
`mcp-drift` user timer (role `mcp_drift`) runs `tools/list` against each live approved server with the export and
hash code above, compares it with the `tools.sha256` copied from this folder, and logs a line per changed, added or
removed tool, and per unapproved server, to Loki (`logger -t mcp-drift`, Grafana "AI inventory"). A new server
needs a folder here **and** an entry in `mcp-servers.yaml`. Details: runbooks/mcp-admission.md.

The `wedding`, `vision-ai` and `home-board` servers were removed from both Hermes profiles on 2026-11-15 (folder
gone, vision skipped, Home Board decommissioned), so they are not exported.
