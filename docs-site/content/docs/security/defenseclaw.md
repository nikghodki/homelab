---
title: "DefenseClaw"
description: "Every DefenseClaw part in the fleet: per-user installs, the Hermes connector, the homelab policy, Fleet, AIBOM, scanners, telemetry, the PATH outage and recovery, upgrades."
---

DefenseClaw 1.0.9 (Cisco AI Defense, open source) guards agents: hook connectors inspect each tool and model call,
scanners check skills and MCP servers, and the Fleet gateway manages small devices. D7 says "use every capability on
every connected agent"; this page says what is actually deployed.

## Where it runs

| Host | Account | Install | Gateway API | Guards | Mode |
|---|---|---|---|---|---|
| Jetson | `nikjetson` | per-user 1.0.9 (`~/.local/bin/defenseclaw`, `~/.defenseclaw/`), user unit `defenseclaw-gateway` | 127.0.0.1:18970 | Hermes main profile (Hermes hook connector) | action, fail closed, HITL at MEDIUM |
| Jetson | `hermes-nikhil` | per-user 1.0.9, own unit | 127.0.0.1:18980 (`gateway.port` 18971) | Hermes profile nikhil-ghodki | same |
| dgx-1 | `nikghodki-dgx` | per-user 1.0.9 (replaced the work-managed 1.0.2 and dcsidecar, P0.5) | 127.0.0.1:18970 | no agents yet; hosts the **Fleet gateway** | — |
| Pi | system user `defenseclaw` | Edge Connector 1.0.9 built from source | — | picoclaw (in-process hook) and Fleet reporting | strict |
| Dell, dgx-2 | — | not installed | — | — | — |
| MacBook Air | — | removed 29 Sep (out of scope) | — | — | — |

DefenseClaw itself is installed by hand with its release installer, per user. Ansible manages the parts around it
(`playbooks/defenseclaw.yml`):

| Role | Does | Where |
|---|---|---|
| `defenseclaw_policy` | copies `policies/defenseclaw/homelab.yaml` to `~/.defenseclaw/policies/`, runs `defenseclaw policy activate homelab` when changed or inactive, then `policy validate` | every account in `defenseclaw_policy_users` (Jetson: `nikjetson`, `hermes-nikhil`), else the login user; skipped where the CLI is absent |
| `defenseclaw_gateway_env` | writes `~/.config/systemd/user/defenseclaw-gateway.service.d/10-path.conf` with `~/.local/bin` on `PATH`, reloads the user manager (no restart) | same accounts; skipped where the unit is absent |
| `defenseclaw_fleet` | Fleet secrets in `~/.defenseclaw/.env`, `fleet.*` config keys via `defenseclaw config set`, restarts the gateway | `defenseclaw_fleet_enabled: true` (dgx-1) |
| `defenseclaw_aibom` | nightly `defenseclaw aibom scan --json` (user timer `homelab-aibom.timer`, 03:15, 30 days kept) | `defenseclaw_aibom_enabled: true` (Jetson, nikjetson) |
| `defenseclaw_policy` (MCP admission part) | merges `asset_policy` from `policies/defenseclaw/mcp-servers.yaml` into `~/.defenseclaw/config.yaml` with `defenseclaw config set --json asset_policy`, then `config validate` | `defenseclaw_policy_mcp_admission: true` (Jetson, both accounts) |
| `mcp_drift` | nightly MCP drift check (user timer `mcp-drift.timer`, ~03:40) | `mcp_drift_enabled: true` (Jetson, both accounts) |

Run: `cd ~/homelab/hosts && ~/.venvs/ansible/bin/ansible-playbook playbooks/defenseclaw.yml --check --diff`.

## The policy `homelab` (`policies/defenseclaw/homelab.yaml`)

Based on the built-in `default` preset. What it sets:

- **Admission:** scan on install; allow-listed items bypass the scan.
- **Skills:** CRITICAL and HIGH → file quarantined, runtime disabled, install blocked. MEDIUM and below → allowed.
- **MCP:** CRITICAL → block at runtime and install, quarantine the file; HIGH → block runtime and install. MEDIUM/LOW
  allowed. Reason: every MCP tool reaches agents through LiteLLM eventually (D20).
- **Plugins:** HIGH → block and quarantine; MEDIUM allowed.
- **First-party allow list:** the DefenseClaw plugin and the `codeguard` skill in their known paths.
- **Guardrail:** block threshold 4, alert threshold 2, HITL on at MEDIUM; pattern lists for injection (HIGH), secrets
  (MEDIUM) and exfiltration (HIGH).
- **Firewall:** default deny; blocks the cloud metadata addresses; allows Anthropic, GitHub, the Go proxy, npm and PyPI
  on 80/443.
- **Watch:** rescans every 30 minutes.
- **Audit:** log all actions and scan results, keep 90 days. No webhooks.

CI test `policies/defenseclaw/tests/test_homelab_policy.py` fails if an edit loosens these rules, or if severity keys
are lowercase. Edit the YAML by hand: `defenseclaw policy edit scanner -p` writes lowercase keys next to the preset's
uppercase ones (upstream issue draft 05).

## MCP admission and the drift check (P4.3, PR #67)

- `policies/defenseclaw/mcp-servers.yaml` is the registry of approved MCP servers with their exact launch:
  `homeassistant` (HTTP `http://localhost:8123/api/mcp/assist`, both accounts) and `picoclaw_only` (stdio: Hermes'
  bundled Node + `picoclaw-hardware-mcp.js`, `hermes-nikhil`). `asset_policy.mode: action`, `registry_required: true`,
  `registry_empty_action: deny`: `defenseclaw mcp set` refuses any server not listed with the **same** URL or full
  command path and argv.
- The **runtime** registry check is off (`runtime_detection.enabled: false`): in 1.0.9 one `mode` covers install and
  runtime, so turning it on would block tool calls of a server already in Hermes. Runtime warnings come from the drift
  check instead.
- Servers added by editing Hermes' `config.yaml` (or `hermes mcp add`) bypass DefenseClaw; only the drift check sees
  them. Add servers with `defenseclaw mcp set`.
- **Drift check** (role `mcp_drift`, per account, files in `~/.local/share/homelab-mcp`): for each server in the
  account's `~/.hermes/config.yaml`, an unlisted or relaunched server is reported as `unapproved` (never started); an
  approved one gets a `tools/list` (stdio with only PATH, HOME and the `drift_check` variables, so PicoClaw starts
  without its MQTT credentials; HTTP with the token from Hermes' config) compared with `tools/<server>/tools.sha256`.
  Journal tag `mcp-drift` → Loki → Grafana "AI inventory". Exit 1 = drift or unapproved (unit still succeeds), 2 =
  a check failed. First run 2026-11-15: no drift (homeassistant 24/24, picoclaw_only 20/20).
- Registry subscriptions (`defenseclaw registry add`) are not used: every fleet server is local.

Runbook: runbooks/mcp-admission.md. Check what an account enforces: `defenseclaw config get asset_policy.mcp --format json`.

## Hermes connector

- The Hermes connector covers **one `HERMES_HOME` per Linux account**. A second Hermes profile in the same account
  stopped the gateway from starting (upstream draft 06). Fix: each profile is its own user (P0.15,
  [Hermes](../agents/hermes.md)).
- Both accounts: action mode, tool calls fail closed (a call while the gateway is stopped is blocked: P0.3
  acceptance), HITL at MEDIUM, OTLP to dgx-2 with `sensitive` redaction.
- DefenseClaw can't scan the Hermes MCP servers that are local/private (a path launcher isn't allowlisted); they're
  kept with a warning.

## Scanners (skill-scanner, mcp-scanner) and the PATH outage

The gateway shells out to `skill-scanner` and `mcp-scanner` in `~/.local/bin`. A systemd **user** unit's PATH doesn't
include `~/.local/bin`. When the scanner isn't found, the scan "fails closed": the policy quarantines **every** skill
it rescans.

What happened (2026-11-15): on the Jetson, 76 of 77 skills were quarantined with
`scanner failure (fail-closed): ... exec: "skill-scanner": executable file not found in $PATH`. Recovery:

1. PATH drop-in for every account (role `defenseclaw_gateway_env`, PR #45), then restart the gateway as each user.
2. Per skill: `defenseclaw skill restore <name>` then `defenseclaw skill unblock <name>`.
3. Where restore refuses (the folder name differs from the skill's `name:`, e.g. `mlops/models/segment-anything` vs
   `segment-anything-model`, or the copy sits under `quarantine/per-source/`, or the agent already recreated the
   folder): copy the quarantine folder back to the recorded original path (`cp -a`; the path is in
   `quarantine_records` in `~/.defenseclaw/audit.db`) and rescan. The stale quarantine record stays listed.
4. A few skills stay blocked for real static findings.

Upstream draft 07 describes this. Status now: the skill scanner runs **static-only** for both Jetson accounts
(`scanners.skill_scanner.use_llm: false`) because the LLM behind LiteLLM is down during the DGXMM work. Static-only is
stricter (it can't clear false positives). After the DGXMM session, as each account:

```bash
defenseclaw setup skill-scanner --use-llm
defenseclaw skill scan all
```

## Fleet gateway (for the Edge Connector)

The Fleet gateway is part of dgx-1's DefenseClaw (`fleet.enabled: true`). It talks MQTT 5 to a dedicated Mosquitto
broker (`fleet.nghodki.ai:8884`, D24) and serves the Fleet API on loopback; a host-network Caddy exposes only
`/api/v1/fleet/*` on `:8971` with TLS. Settings written by `defenseclaw_fleet`:

| Key | Value |
|---|---|
| `fleet.mqtt_broker_url` | `ssl://fleet.nghodki.ai:8884` |
| `fleet.mqtt_require_tls` | true |
| `fleet.trust_proxy_headers` | true (only loopback peers, i.e. fleet-caddy, may claim HTTPS) |
| `fleet.allow_key_over_http` | false |
| `fleet.auto_register` | false |
| `.env`: `DCLAW_FLEET_API_URL` | `https://fleet.nghodki.ai:8971/api/v1/fleet` |
| `.env`: `DCLAW_MQTT_USER` | `dclaw-fleet` |
| `.env` secrets | `DCLAW_FLEET_API_TOKEN`, `DCLAW_OTA_HMAC_KEY`, `DCLAW_EMERGENCY_KEY`, `DCLAW_AUDIT_KEY`, `DCLAW_MQTT_PASS` from `secrets/fleet.enc.yaml` |

Details, device registration and limits: [Edge Connector and Fleet](edge-connector.md).

## AIBOM and AI discovery

- **DefenseClaw AIBOM** (Jetson, nikjetson): what Hermes has connected (skills, plugins, MCP servers, memory, rules).
  Reports in `~/.local/state/homelab-aibom/`, summary to the journal (`SyslogIdentifier=homelab-aibom`) → Loki.
- **Cisco AIBOM** is a different tool (static analysis of code and images): [Scanning](scanning.md).
- AI discovery runs inside each gateway; its dashboards ("AI Agent Usage & Detection", "AI Discovery Runtime Planes")
  are provisioned. Shadow-AI alerting is not wired (unverified).

## Telemetry

Gateways send OTLP to dgx-2's `otel-defenseclaw` collector (4317 gRPC / 4318 HTTP): logs → Loki, traces → Tempo,
metrics → VictoriaMetrics. The collector config is DefenseClaw's own (adapted, `hosts/stacks/observe/otel-defenseclaw/`).
All 19 DefenseClaw dashboards and its alert rules are vendored ([Dashboards](../observability/dashboards.md),
[Alert rules](../observability/alert-rules.md)).

## Not used (and why)

| Capability | Status |
|---|---|
| Webhooks (HITL → WhatsApp/ntfy) | dropped: DefenseClaw refused private receivers (P1.11) |
| LLM judge | on since 2026-11-15 (`guardrail.judge.enabled`) on the Jetson (both users, key `defenseclaw-jetson-judge`) and dgx-1 (key `defenseclaw-dgx1`), model `qwen3.8-27b` via LiteLLM |
| OpenShell sandboxes | not set up (`Sandbox: off`) |
| Tetragon kernel controls | not installed (P3.6) |
| Agent-gateway route for LiteLLM | on since 2026-11-15 on dgx-1 (`connectors.agent_gateway.enabled`, action mode); LiteLLM's global guardrail (`hosts/files/litellm/defenseclaw_guardrail.py`, 10 tests) blocks prompt injection with HTTP 400 (P2.4) |
| ACP guard, semantic routing, Splunk/Galileo | not used |

## Upgrade DefenseClaw

1. Renovate opens a PR bumping `version` in `hosts/stacks/observe/defenseclaw-bundle.yaml` (no automerge).
2. On dgx-1, on that branch: `.github/scripts/defenseclaw-bundle.py sync`. It copies the vendored dashboards and rules
   from the release and prints upstream diffs for the adapted files (`loki.yaml`, `tempo.yaml`, `otel-defenseclaw`);
   port them by hand, push.
3. CI's `defenseclaw-bundle.py check` must pass. Merge, `playbooks/observe.yml`.
4. Upgrade each per-user install with the release installer (as each user), then the Edge Connector on the Pi and the
   gateway together (the signed heartbeat format changes between releases). Re-run `playbooks/defenseclaw.yml`.
5. Check the umask fix on dgx-1 after uv installs a new Python ([Troubleshooting](../operations/troubleshooting.md)).
