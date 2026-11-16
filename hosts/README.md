# hosts

Ansible inventory and roles for every device (plan P1.3): base hardening, Tailscale, unattended security upgrades,
the OTel collector, DefenseClaw (connector or Edge Connector per host) and Lynis. (Tetragon is planned, P3.6.)

| Host | Role | Notes |
|---|---|---|
| dgx-1 | Interactive models, k3s server | GB10, 121 GiB |
| dgx-2 | Batch, simulation, observability, k3s server | GB10, 121 GiB |
| jetson | Home + robot brain, etcd member + tainted k3s worker (D2 refined, #40) | Orin, 7.4 GiB |
| omarchy | Alerting (Gatus, ntfy), Homepage, docs site; k3s agent; OpenBot + workers later | Dell Inspiron 7348, x86 |
| nikghodki-raspberry | Robot body (Ansible only, not in k3s) | Pi 4, user `nikghodki-raspberry-1` |

Playbooks always run in check mode first.

## Running

From dgx-1, in this folder (`hosts/`):

```bash
~/.venvs/ansible/bin/ansible-galaxy collection install -r requirements.yml
~/.venvs/ansible/bin/ansible-playbook playbooks/site.yml --check --diff   # always first
~/.venvs/ansible/bin/ansible-playbook playbooks/site.yml --limit <host>    # then apply, one host at a time
```

Roles today (31, `roles/`): host basics (`base`, `hardening`, `lynis`, `tailscale`, `tailscale_serve`, `homelab_ca`,
`retired_units`, `always_on`, `flannel_offload_fix`, `jetson_cdi`), metrics and logs (`fleet_metrics`,
`otel_host_collector`), Docker stacks (`compose_stack`, `docs_site`), the cluster (`k3s`), DefenseClaw and AI inventory
(`defenseclaw_gateway_env`, `defenseclaw_policy`, `defenseclaw_fleet`, `defenseclaw_aibom`, `edge_connector`,
`cisco_aibom`, `mcp_drift`), the robot (`picoclaw`, `safety_governor`, `hermes_robot_mcp`, `ros_lidar`,
`ros_zenoh_router`), the Jetson's services (`livekit`) and backups (`restic_install`, `restic_backup`,
`restic_prune`; off by decision 0002). Tetragon is planned (P3.6).

`k3s` (`playbooks/k3s.yml`): the cluster (plan P3.2), servers on the Sparks, etcd member + tainted worker on the Jetson, agent on
Omarchy; pinned version, checksum-verified binary. See [runbooks/k3s.md](../runbooks/k3s.md).

`lynis` (`playbooks/lynis.yml`): weekly `lynis-audit.timer` (Sunday 03:30, idle CPU and I/O priority). The wrapper
`/usr/local/sbin/lynis-audit` logs `hardening_index=N warnings=W ...` and one line per warning to the journal with tag
`lynis`; the host collector ships them to Loki, and Fleet Home shows the latest index per host.

`ops_agent_access` (`playbooks/ops-agent-access.yml`, decision 0013): the ops agent's read-only user `opsro` on every
host, with the forced-command allowlist `/usr/local/sbin/ops-ro` (redacted, capped, rate-limited, logged with tag
`ops-ro`) and a re-validating root helper for Docker and certificate expiry. No act user. See
[runbooks/ops-agent.md](../runbooks/ops-agent.md#host-access-opsro).
