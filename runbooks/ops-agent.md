# Ops agent

The ambient operations agent ([design](../docs/ambient-agent-design.md), [decision 0013](../decisions/0013-ambient-ops-agent.md)).
Each section below is self-contained; other parts of the agent add their own.

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
