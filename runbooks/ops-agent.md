# Ops agent

The ambient operations agent ([design](../docs/ambient-agent-design.md), [decision 0013](../decisions/0013-ambient-ops-agent.md)).
Each section below is self-contained; other parts of the agent add their own.

**Mode: shadow (S1).** It watches, investigates with read-only tools and the local model, writes RCAs and
postmortems into its own database, and notifies on its own ntfy topic. It has **no write access anywhere**: no
GitHub write, no restarts, no syncs, no silences. Promotion past shadow (PRs, then live actions) waits for your review.

| Piece | Where |
|---|---|
| Code | `agents/ops-agent` (one image, `ghcr.io/nikghodki/ops-agent`, built and signed by `build-sign.yml`) |
| Workloads | `cluster/apps/ops` (Argo CD app `ops`): `ops-ingest` (2), `ops-worker` (2), `ops-portal` (2), the read-only MCP servers, CNPG `ops-db` (2 instances) |
| Cluster reader | ClusterRole `ops-agent-read` (`cluster/platform/ops-agent-rbac`, app `ops-agent-rbac`): get/list/watch, no Secrets, no exec |
| Portal | **https://ops-agent.nghodki.ai** (front-door sign-in, `admins`): Feed, Incident, Replay, Audit, Stop |
| Workflows | Temporal on dgx-2, namespace `ops-agent`, client certificate `ops-agent.crt` (writer on that namespace only; runbooks/temporal.md) |
| Model | LiteLLM key `ops-agent`: `qwen3.8-27b` and `-nothink` only, 30 rpm, 150k tpm, 2 in flight; the agent's own budget: 1 M tokens/day, 150k and 25 tool calls per incident, 2 investigations at once |
| Notifications | ntfy topic **`ops-agent`** (user `ops-agent` may only write; `nikhil` reads) |
| Kill switch | the portal's **Stop** button, or `mode: stopped` in `cluster/apps/ops/mode.txt` (the stricter one wins) |
| Watchers | Gatus group `ops-agent` (portal, portal health, ingest, worker heartbeat); vmalert `ops-agent.yml` |
| Credentials | `cluster/apps/ops/ops-agent.enc.yaml` (KSOPS): LiteLLM key, Grafana Viewer token, Argo CD readonly token, MCP server tokens, Temporal cert, opsro key, deploy key, ntfy token, heartbeat token, ingest token, the front door's origin token. Sources in `secrets/{litellm,observe,argocd,pki,ops-agent}.enc.yaml` |

### What it watches

- **Alertmanager**: a receiver `ops-agent` at the top of the route tree with `continue: true`, so every existing
  ntfy route sees the same alerts as before. Alerts labelled `ops_agent_only` (`GatusEndpointFailing`, which would
  duplicate Gatus' own ntfy alerts) stop at the `null` receiver after it. Alertmanager runs with
  `receiver-name-in-metrics`, and `AlertDeliveryFailing` ignores receiver `ops-agent`: the agent being down never
  pages through the public ntfy.sh fallback.
- **Gatus** results through VictoriaMetrics (`GatusEndpointFailing`, `for: 3m`).
- **Kubernetes Warning events** (BackOff, OOMKilled, FailedScheduling, FailedMount, repeated Unhealthy, Kyverno
  PolicyViolation), watched by one ingest replica at a time (Postgres advisory lock).
- **Changes**: merges to `main` (a read-only clone with the deploy key `ops-agent`) and Argo CD syncs; an incident
  within 20 minutes after a change to the same component is tagged `during-change`.
- **CI**: GitHub Actions runs through the public API (the repo is public; without a token a private repo turns the
  poller off). Failures with 0 steps are classed `infra` (billing, runner), the rest `check`. Reported only.

Correlation: one open incident per key; a host that is down collects every event on it; more than 10 new events in
5 minutes is one storm incident; an alert that fires more than 5 times an hour becomes one "flapping" item.

### Investigation

First look (fixed queries per class, `agents/ops-agent/ops_agent/playbooks/first_look.yaml`) -> recall (runbook
search, past incidents) -> the model with the read-only tools (metrics, logs, k3s, Argo CD, `ops-ro` host commands, CI,
runbooks, past incidents, changes) -> RCA with cited evidence (uncited claims are removed) and a second look. Every
tool result is redacted, capped, stored as an evidence item (E1, E2, ...) with a Grafana/Argo CD/GitHub link where
there is one, and fenced as data. When the model is down or the budget is used up, the RCA is the evidence without
analysis (decision 0013 Q6: fixed queries only, no cloud model).

### Notifications (decision 0013 Q9, Q10)

| What | When |
|---|---|
| Family-facing incident (Home Assistant, Open WebUI, DNS, the front door) | at once, urgent, also in quiet hours |
| Critical RCA ready | at once (high); in quiet hours 22:30-07:30 held until 07:30 |
| Everything else | in the 08:00 digest |

Buttons: **Open** (the portal), **Snooze 1 h** and **Dismiss** (`/ntfy-action/<token>`, a random token per message
for one incident; they only make the agent quieter). Never an Approve button.

**On the phone**: in the ntfy app, add topic `ops-agent` on the same server as `fleet-alerts`
(`https://nikghodki-omarchy-1.tail1cb707.ts.net`, user `nikhil`).

### Stop

Portal -> **Stop**: the workers cancel every running incident workflow, stop polling Temporal (no new
investigations, no model calls, no SSH), ingest keeps recording events without starting workflows, and the heartbeat
reports "agent stopped". **Resume** in the portal (type `resume`). From Git: `mode: stopped` in
`cluster/apps/ops/mode.txt`, merge (the pods roll with the new ConfigMap). Last resort:
`kubectl -n ops scale deploy ops-worker ops-ingest --replicas 0` (Argo CD scales them back unless you stop its sync).

### Replay (A0)

`agents/ops-agent/ops_agent/replay/`: the gold set (`gold.yaml`, seven past incidents with their expected RCAs) and
the harness. It runs on dgx-1 against the agent's database (`10.43.0.143`) and the MCP servers on their fixed
ClusterIPs, with the clock set back to each incident (metrics and logs stop there, the runbooks are the commit that was
on `main` then, live-only tools answer from recorded output):

```bash
agents/ops-agent/dev-env.sh python -m ops_agent replay run --engine own-loop      # or --engine holmesgpt
agents/ops-agent/dev-env.sh python -m ops_agent replay show <run>                 # RCA next to the gold
agents/ops-agent/dev-env.sh python -m ops_agent replay score <run> G1 --root-cause yes --correct 4 --total 5
```

(`dev-env.sh` puts the agent's credentials in a private temp dir for the duration of the command; it needs
`~/.venvs/ops-agent` with the agent's requirements, and HolmesGPT in `~/.venvs/holmes` for that engine. Replays use their
own LiteLLM key, `ops-agent-eval` (1 request in flight), and count their tokens apart from the live budget (engines
`replay-*`, `REPLAY_DAILY_TOKEN_BUDGET`, default 1 M); they never take the live key's two slots.) Results: the
portal's Replay page and the design's §11.5.

### Troubleshooting

- No incidents although alerts fire: `kubectl -n ops logs deploy/ops-ingest`; Alertmanager's
  `alertmanager_notifications_failed_total{receiver_name="ops-agent"}`; Gatus `ops-ingest`.
- Incidents stay "open" without an RCA: the worker isn't polling (portal mode STOPPED, or
  `kubectl -n ops logs deploy/ops-worker`), Temporal unreachable (certificate, runbooks/temporal.md), or the budget
  is used up (header of the portal).
- RCAs say "evidence collected, no model analysis": the model plane was down or answered 5xx (the loop retries
  three times), or DefenseClaw refused a prompt built from the evidence (the RCA notes say so).
- Portal 403 "Use https://ops-agent.nghodki.ai": the request didn't come through the front door, or the origin token
  differs (rotate it with the others: runbooks/sign-in.md, then update `origin-token` in `ops-agent.enc.yaml`).

### Rotate

LiteLLM key (runbooks/litellm.md "Rotating a virtual key"), Grafana token (Grafana -> Service accounts -> ops-agent),
Argo CD token (runbooks/argocd.md), Temporal certificate (`hosts/files/pki/temporal/issue.sh client ops-agent
ns:ops-agent:writer`), opsro key (below), deploy key (`gh repo deploy-key`), ntfy token and heartbeat token
(`secrets/observe.enc.yaml`, then `playbooks/alerting.yml`): each time also update `cluster/apps/ops/ops-agent.enc.yaml`
and merge. Every 90 days.

## Host access (opsro)

The agent reads hosts through one SSH user, `opsro`, on all five hosts (dgx-1, dgx-2, Jetson, the Dell, the Pi),
deployed by `hosts/playbooks/ops-agent-access.yml` (role [`ops_agent_access`](../hosts/roles/ops_agent_access/README.md)).
There is no act user: in shadow mode nothing it can run changes state.

| Piece | Where |
|---|---|
| Private key | `opsro_ssh_key` in `secrets/ops-agent.enc.yaml` (SOPS; only the agent's `ops-ro` tool gets it) |
| Public key, `from=` list | `hosts/roles/ops_agent_access/defaults/main.yml` |
| Forced command | `/usr/local/sbin/ops-ro` (allowlist dispatcher, Python stdlib) |
| Root helper | `/usr/local/libexec/ops-ro-root` (`containers`, `container-logs <name>`, `certs`; re-validates its arguments); sudoers `/etc/sudoers.d/ops-ro` allows only it |
| Per-host lists | `/etc/ops-agent/certs` (`ops_agent_access_certs` in host_vars, k3s certs added by group), `/etc/ops-agent/defenseclaw` (`ops_agent_access_defenseclaw_ports`) |
| Audit | journal tag `ops-ro` on each host (verb, args, exit code, bytes, redaction count, source IP; never the output); shipped to Loki by the host collector |

**Verbs** (`ssh opsro@<host> <verb> [args]`; `help` lists them): `help`, `health`, `units`, `status <unit>`,
`journal <unit> <since>`, `kernel <since>`, `kernel-prev`, `containers`, `container-logs <container>`, `gpu`, `net`,
`k3s [<since>]`, `certs`, `defenseclaw`. Names match `^[a-zA-Z0-9][a-zA-Z0-9@._-]{0,63}$`; `<since>` is `-30m`, `-2h`,
`-1d` (at most 7 days) or an ISO time (no offset means UTC). Anything else is refused with exit 2; more than 60 calls
a minute on one host is refused with exit 3. Output is redacted (private keys, Authorization/Bearer, `password=`,
`token=`, `secret=`, `*_key=` values, URL passwords, AWS, `sk-`, GitHub/Slack tokens, JWTs, long high-entropy strings)
and capped at 64 KB (`[truncated]`). `defenseclaw` reads only `GET /health` of the gateways on loopback and prints
states and counters (no config, no audit DB). `gpu` uses `nvidia-smi` on the Sparks and sysfs on the Jetson.

**Where the key works from** (`from=` in `authorized_keys`): `192.168.86.44`, `192.168.86.36` (the Sparks' LAN
addresses), `10.42.0.0/16` (pods talking to their own node), `10.100.136.1`, `10.100.136.2` (the Spark-to-Spark link),
`127.0.0.1`. Pod egress to the LAN is masqueraded to the node's LAN address (flannel `FLANNEL-POSTRTG`); checked on
2026-11-16 with a probe pod on each Spark: other hosts' sshd saw `192.168.86.36`/`.44`, the pod's own node saw the pod
address. Tailscale addresses are not listed: the agent must use LAN addresses. The Dell's UFW `LIMIT` on 22 exempts
dgx-1 and dgx-2 (`hardening_ufw_ssh_allow`), so the agent's bursts aren't throttled there.

**Checks**

```bash
ssh -i <key> opsro@192.168.86.36 help             # verb list
ssh -i <key> opsro@192.168.86.36 env              # refused, exit 2
sudo journalctl -t ops-ro --since -1h             # on the host: who asked what
```

**Rotate the key**: generate a new ed25519 key in a private temp folder on dgx-1, put the public key in
`ops_agent_access_pubkey`, the private key with
`python3 -c 'import json,sys; print(json.dumps(open(sys.argv[1]).read()))' <file> | sops set --value-stdin secrets/ops-agent.enc.yaml '["opsro_ssh_key"]'`,
remove the folder, PR, run the playbook (`--check --diff` first), update the agent's Secret.

**Revoke at once**: on each host `sudo truncate -s 0 /var/lib/opsro/.ssh/authorized_keys` (the next playbook run
restores it, so also change Git). **Remove**: delete the user and the files listed above.

**Add a verb**: only read-only commands with fixed argument shapes; extend `VERBS` and `execute()` in
`files/ops-ro.py` (and `ops-ro-root.py` if it needs root, re-validating there too), add tests in
`files/tests/test_ops_ro.py`, PR.
