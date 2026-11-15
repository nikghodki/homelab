# hosts

Ansible inventory and roles for every device (plan P1.3): base hardening, Tailscale, unattended security upgrades,
the OTel collector, DefenseClaw (connector or Edge Connector per host), Tetragon and Lynis.

| Host | Role | Notes |
|---|---|---|
| dgx-1 | Interactive models, k3s server | GB10, 121 GiB |
| dgx-2 | Batch, simulation, observability, k3s server | GB10, 121 GiB |
| jetson | Home + robot brain, etcd-only member | Orin, 7.4 GiB |
| omarchy | OpenBot + workers, k3s agent | Dell Inspiron 7348, x86 |
| nikghodki-raspberry | Robot body (Ansible only, not in k3s) | Pi 4, user `nikghodki-raspberry-1` |

Playbooks always run in check mode first.

## Running

From dgx-1, in this folder (`hosts/`):

```bash
~/.venvs/ansible/bin/ansible-galaxy collection install -r requirements.yml
~/.venvs/ansible/bin/ansible-playbook playbooks/site.yml --check --diff   # always first
~/.venvs/ansible/bin/ansible-playbook playbooks/site.yml --limit <host>    # then apply, one host at a time
```

Roles today: `base` (time zone, journal cap, SSH hardening drop-in, security-only upgrades), `tailscale`
(installed, running, logged-in report), `fleet_metrics` (probe). More roles follow the plan: DefenseClaw, OTel
collector, Tetragon, Lynis.

`k3s` (`playbooks/k3s.yml`): the cluster (plan P3.2), servers on the Sparks, etcd-only member on the Jetson, agent on
Omarchy; pinned version, checksum-verified binary. See [runbooks/k3s.md](../runbooks/k3s.md).

`lynis` (`playbooks/lynis.yml`): weekly `lynis-audit.timer` (Sunday 03:30, idle CPU and I/O priority). The wrapper
`/usr/local/sbin/lynis-audit` logs `hardening_index=N warnings=W ...` and one line per warning to the journal with tag
`lynis`; the host collector ships them to Loki, and Fleet Home shows the latest index per host.
