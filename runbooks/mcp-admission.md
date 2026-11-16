# MCP admission and drift (plan P4.3)

Which MCP servers the Jetson's Hermes profiles may use, how DefenseClaw enforces that, and the nightly check that
the servers still offer the tool definitions that were reviewed.

| Piece | Where | What it does |
|---|---|---|
| Approved servers | `policies/defenseclaw/mcp-servers.yaml` | `asset_policy` for DefenseClaw (registry of servers with their exact launch) and the probe settings for the drift check |
| Pinned tools | `tools/<server>/tools.json`, `tools.sha256` | The reviewed `tools/list` and one sha256 per tool (tools/README.md) |
| Admission | role `defenseclaw_policy` (`defenseclaw_policy_mcp_admission: true` in `host_vars/jetson.yml`) | Merges `asset_policy` into `~/.defenseclaw/config.yaml` of `nikjetson` and `hermes-nikhil` with `defenseclaw config set --json asset_policy` |
| Drift check | role `mcp_drift` (`mcp_drift_enabled: true`), user timer `mcp-drift.timer` (~03:40) per account | `tools/list` against each live approved server, compared with `tools.sha256`; Hermes' configured servers compared with the registry |
| Dashboard | Grafana "AI inventory", panels "MCP drift findings, last 2 days" and "MCP drift (Jetson, mcp-drift)" | Loki, `SYSLOG_IDENTIFIER=mcp-drift` |
| CI | `pr-checks.yml`: `mcp-tool-hashes.py check`, `scan-mcp-tools.py` (mcp-scanner, static), `hosts/roles/mcp_drift/files/tests`, `policies/defenseclaw/tests` | A changed tool must come with a changed hash; the registry launch must match `tools/<server>/server.yaml` |

Approved now: `homeassistant` (HTTP, `http://localhost:8123/api/mcp/assist`) on both accounts and `picoclaw_only`
(stdio, Hermes' bundled Node + `picoclaw-hardware-mcp.js`) on `hermes-nikhil`.

## How DefenseClaw 1.0.9 admits MCP servers

- `asset_policy.mcp.registry` lists the approved servers. With `registry_required: true` and `asset_policy.mode:
  action`, `defenseclaw mcp set` refuses any server that is not listed with the **same launch**: the exact URL, or
  the full command path and exactly the listed argv (`args_prefix`, matched strictly for the registry). Reusing an
  approved name with another URL, another `node` binary or an extra argument is refused too.
- The runtime registry check is **off** (`asset_policy.mcp.runtime_detection.enabled: false`): DefenseClaw's
  agent hooks then apply only the `asset_policy.mcp.denied` list. In 1.0.9 one `mode` covers both install and
  runtime, so `action` with runtime detection on would also block tool calls of a server already in Hermes; we
  prefer to warn at runtime. The warning comes from the nightly drift check (an unapproved server is logged and
  shown on the dashboard).
- Servers added by editing Hermes' `config.yaml` (or `hermes mcp add`) do not pass through DefenseClaw at all;
  only the drift check sees them. Add servers with `defenseclaw mcp set` so the registry applies.
- DefenseClaw's own scanner can't scan these two servers (a stdio server that isn't started with npx/uvx, and a
  loopback URL), so its watcher keeps them "with a warning". The review is the mcp-scanner run in CI on the
  exported `tools.json` plus the hashes.
- Registry subscriptions (`defenseclaw registry add`, Smithery and others) are not used: every fleet server is
  local, and a synced entry is only promoted after a scan or a local `registry approve`, which would not be in Git.

Check what an account enforces (read-only):

```bash
defenseclaw config get asset_policy.mcp --format json
defenseclaw config get asset_policy.mode
```

Test a change without touching the live Hermes: copy `~/.defenseclaw/config.yaml` and `~/.defenseclaw/policies`
into a temporary folder (change `port:` and the `custom_packs` path to that folder), copy `~/.hermes/config.yaml`
into another, then `DEFENSECLAW_HOME=<dc copy> HERMES_HOME=<hermes copy> defenseclaw mcp set dummy --url
http://127.0.0.1:9/mcp --skip-scan --connector hermes` must print `blocked [hermes]: mcp 'dummy' is not in the
approved registry`. Delete both copies afterwards.

## Adding or changing a server

1. On the Jetson, export the server's tools (tools/README.md) into `tools/<name>/`, with a `server.yaml` that has
   the launch.
2. Add the server to `asset_policy.mcp.registry` in `policies/defenseclaw/mcp-servers.yaml` with the same launch
   (`url`, or `command` + `args_prefix`), and under `drift_check` the environment that starts it without
   credentials, if it is stdio.
3. Run `.github/scripts/mcp-tool-hashes.py update`, read the diff, open a PR. CI checks the hashes, scans the tools
   and checks that the registry launch matches `server.yaml`.
4. After the merge: `ansible-playbook playbooks/defenseclaw.yml --limit jetson` (from `hosts/`, Ansible venv),
   then `defenseclaw mcp set <name> ...` as the account, restart its `hermes-gateway`, and run the drift check
   once.

Removing a server: delete it from Hermes (`defenseclaw mcp unset <name>`, or edit `config.yaml` after a backup),
then from `mcp-servers.yaml` and `tools/`, and re-run the playbook.

## Drift check

Runs as each account in `defenseclaw_policy_users` (user unit, files in `~/.local/share/homelab-mcp`: the repo's
`tools/`, `mcp-servers.yaml`, and the same `export-mcp-tools.py` / `mcp-tool-hashes.py` CI uses). For each server
in the account's `~/.hermes/config.yaml`:

- not in the registry, or a different launch: `mcp-drift.server` with `change: unapproved` (warning). The server is
  **not started** by the check.
- approved: `tools/list` (stdio with only PATH, HOME and the `drift_check` variables, so PicoClaw starts without
  its MQTT credentials; HTTP with the `Authorization` header from Hermes' config, `${HA_TOKEN}` read from
  `~/.hermes/.env`, never logged), then one `mcp-drift.tool` line per changed, added or removed tool and one
  `mcp-drift` line per server (`status: ok|drift|error`, counts).
- one `mcp-drift.run` line per account (`status`, `checked`, `drift`, `unapproved`, `errors`).

Exit 0 = ok, 1 = drift or unapproved (unit still succeeds), 2 = a server could not be checked (unit fails).

```bash
# run it now (as the account; nikjetson shown)
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user start mcp-drift.service
journalctl -t mcp-drift --since -10min -o cat
# or print only, without writing to the journal
python3 ~/.local/bin/mcp-drift --no-logger
```

First run, 2026-11-15: no drift. `nikjetson`: homeassistant 24/24 tools ok. `hermes-nikhil`: homeassistant 24/24,
picoclaw_only 20/20 ok. A test copy with one tampered hash reported `battery_status` changed and exited 1.

### When it reports drift

- **changed / added / removed tool**: the server now offers a different definition than the reviewed one. Treat it
  as a possible tool-poisoning or rug pull until reviewed: compare a fresh export with `tools/<name>/tools.json`
  (`export-mcp-tools.py`, tools/README.md). If the change is expected (a Home Assistant entity exposed or renamed,
  a roboclaw update), commit the new export and hashes in a reviewed PR and re-run the playbook. If not, remove
  the server from Hermes (back up `config.yaml`, restart `hermes-gateway`) and investigate.
- **unapproved**: a server is in Hermes' config that is not in `mcp-servers.yaml`, or an approved name runs with
  another launch. Remove it, or add it through the steps above.
- **error**: the server didn't answer (Home Assistant down, PicoClaw script missing, Node moved). Fix the server; if
  its launch changed, that is a registry change (above).
