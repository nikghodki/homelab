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

CI (`ai-scanners` job):

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

Not exported yet: the `wedding`, `vision-ai` and `home-board` servers in Hermes' config (the Home Board is
decommissioned), and a live nightly comparison against the running servers (needs a job on the Jetson).
