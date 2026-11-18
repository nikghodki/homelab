# DefenseClaw weekly LLM rescan (2026-11-17)

DefenseClaw's `watch` used to re-scan every skill, plugin and MCP server with the LLM analyzer (`qwen3.8-27b`
through LiteLLM) **every 30 minutes, around the clock**. On the Jetson that made `defenseclaw-jetson-judge` the
fleet's dominant model caller (~2,000 requests/24 h, one burst of ~130 LLM calls per 30 min). The repeated re-scan
of already-scanned assets is now a **single weekly LLM rescan at a fixed time**: Sunday 02:00 local (all hosts are
`America/Los_Angeles`), run by a systemd user timer per DefenseClaw account.

| Piece | Where | What it does |
|---|---|---|
| Policy `watch` | `policies/defenseclaw/homelab.yaml` (applied to every `homelab`-policy account by role `defenseclaw_policy`) | `rescan_enabled: false`, `rescan_interval_min: 10080` — the gateway's own periodic LLM rescan is off; the timer is the only recurring one |
| Timer | role `defenseclaw_rescan`, user timer `homelab-rescan.timer` (Sunday 02:00, +10 min random delay, `Persistent`) | `~/.local/bin/homelab-rescan` runs the same scan pass the watch ran: `skill scan --all --use-llm`, `plugin scan --all --use-llm`, `mcp scan --all` |
| Accounts | `defenseclaw_rescan_enabled: true` + `defenseclaw_rescan_users` in `host_vars/`: Jetson (`nikjetson`, `hermes-nikhil`), dgx-1 (login user) | One timer per per-user DefenseClaw install; the Pi edge connector has no LLM judge and is not in scope |
| Logging | journal tag `homelab-rescan` → host collector → Loki | One JSON summary line per run: per-category `targets`, `findings`, `severe_findings` (CRITICAL/HIGH), `errors`, `duration_s` |
| CI | `pr-checks.yml`: `hosts/roles/defenseclaw_rescan/files/tests` | Scan commands, JSON parsing, summary shape, exit codes (CLI faked) |

## What is and is not slower now

- **Slower (the point):** the *repeated* LLM re-scan of existing skills/plugins/MCP — 30 min → once a week, at
  Sunday 02:00. That is the load that showed up as `defenseclaw-jetson-judge` in the spend logs and the
  "Model API callers" dashboard.
- **Not slower:** new installs are still scanned **on install** (`admission.scan_on_install: true`); new AI
  components are still discovered continuously (`ai_discovery`, 5 min, unchanged — and its upstream
  `DefenseClawAIDiscoveryStalled` alert stays honest); the guardrail judge still runs on every tool call and
  prompt; the nightly AIBOM (03:15) and MCP drift check (~03:40) are untouched. The trade-off is that a *modified*
  existing asset is LLM-re-checked at most weekly instead of every 30 min.
- **Known normal state:** the MCP scan refuses loopback/private URLs by default (SSRF guard), so the Jetson's
  `homeassistant` MCP records `refusing to scan MCP URL 'http://localhost:8123…'` with exit 1 on every pass — the
  gateway's watch did exactly that every 30 min too. `homelab-rescan` keeps that scope (no `--allow-private`), so
  `errors: 1` and exit code 1 on the Jetson are expected, not failures. The unit carries `SuccessExitStatus=1`.

## Check

```sh
# next run and last run (as the account; linger is on, so the user manager runs unattended)
systemctl --user list-timers homelab-rescan.timer --no-pager
# the one-line summary of the last run (journal tag homelab-rescan; shipped to Loki)
journalctl --user -t homelab-rescan -n 3 --no-pager
# trigger one now (runs the full LLM pass; a few minutes warm, the model is on demand)
systemctl --user start homelab-rescan.service && systemctl --user status homelab-rescan.service --no-pager
# what it calls and how it is scheduled (files are managed by Ansible; do not edit by hand)
cat ~/.config/systemd/user/homelab-rescan.{service,timer}
```

Model load after a run shows in the spend logs / "Model API callers" dashboard as `defenseclaw-jetson-judge`
(Jetson) or `defenseclaw-dgx1` (dgx-1) — a single burst of a few dozen requests per account, once a week.

## Why the policy and not `config set`

`defenseclaw policy activate homelab` overwrites `watch.rescan_interval_min` in the account's
`~/.defenseclaw/config.yaml` (checked 2026-11-17: a `config set watch.rescan_interval_min` reverts to the policy
value on the next activate). The policy file is the only durable source, and it is applied to every account the
playbook manages — which is why the change lives in `policies/defenseclaw/homelab.yaml` and lands on all
`homelab`-policy hosts (Jetson both accounts, dgx-1) with one edit. The CI policy test
(`policies/defenseclaw/tests`) does not pin `watch`, so nothing guards it against drift.

## Roll back (restore the 30-min rescan, drop the timer)

```sh
cd ~/homelab && git checkout HEAD -- policies/defenseclaw/homelab.yaml hosts/host_vars/jetson.yml hosts/host_vars/dgx-1.yml
cd hosts && ~/.venvs/ansible/bin/ansible-playbook playbooks/defenseclaw.yml   # re-applies the policy (watch back on)
# then, per account, stop the timer (the role does not remove it when disabled)
systemctl --user disable --now homelab-rescan.timer
```

(Or revert the PR and let the next `defenseclaw.yml` run do the policy part; the timer stops via `--now` as above.)

## Deploy (this change, 2026-11-17)

1. PR with: policy `watch` off + 7-day cadence, the `defenseclaw_rescan` role, the timer unit, `host_vars`
   enablement, the playbook wiring, the CI step, this runbook and decision 0015.
2. Merge; run `playbooks/defenseclaw.yml` from dgx-1 (it activates the policy on every account — the gateway
   reloads and the 30-min loop stops — and installs the timer; the first scan is the next Sunday 02:00).
3. Verify: `systemctl --user list-timers homelab-rescan.timer` shows Sunday; the spend logs show the
   `defenseclaw-jetson-judge` cadence dropping from ~87/hour to ~0 between Sundays; the `ai_discovery` stalled
   alert stays quiet (discovery is still 5 min).
