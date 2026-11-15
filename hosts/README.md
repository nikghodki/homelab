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
