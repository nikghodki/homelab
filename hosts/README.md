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
