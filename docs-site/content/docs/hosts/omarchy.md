---
title: "Omarchy (the Dell)"
description: "The Dell Inspiron 7348 running Omarchy: the alerting path (Gatus, ntfy), the Homepage launcher, and a k3s agent. It never sleeps."
---

The Dell is the weakest machine, but it has one important job: it carries the alerting path, so alerts still reach the
phone when both Sparks crash. It was made "always on" for that (PR #55, role `always_on`).

## Hardware and OS

| | |
|---|---|
| Hostname | `nikghodki-omarchy-local` |
| Hardware | Dell Inspiron 7348 (2015): i5-5200U (2 cores, 4 threads), 8 GB soldered (one slot, 8 GB max), 500 GB 5400 rpm HDD (root on `/dev/mapper/root`), Wi-Fi only |
| OS | Omarchy (Arch Linux), kernel 7.2.15-2-omarchy, Hyprland desktop |
| User | `nikghodki` |
| LAN | `wlp1s0` 192.168.86.49 |
| Tailscale | 100.117.118.69, `nikghodki-omarchy-1.tail1cb707.ts.net` (the `-1` suffix is Tailscale's), `tag:agent` |

## What runs here

| Stack / unit | Containers | Published | Playbook |
|---|---|---|---|
| `alerting` | `alerting-gatus-1` (Gatus 5.38.0), `alerting-status-gate-1` (Caddy 2.11.9), `alerting-ntfy-1` (ntfy 2.38.0) | 127.0.0.1:8082 (Gatus), 192.168.86.49:8081 (status-gate), 127.0.0.1:8085 and 192.168.86.49:8085 (ntfy) | `alerting.yml` |
| `ops` | `ops-homepage-1` (Homepage 2.8.0), `ops-docs-1` (Caddy 2.11.9: docs site and Homepage's gate) | 192.168.86.49:4180 (Homepage), :4181 (docs) | `ops.yml` |
| `tailscale serve` | `https://nikghodki-omarchy-1.tail1cb707.ts.net` → `http://127.0.0.1:8085` (ntfy, tailnet only) | 443 on the tailnet | role `tailscale_serve` |
| `k3s-agent.service` | k3s agent, node IP 192.168.86.49 | 10250 | `k3s.yml` |
| `otelcol-contrib`, `fleet-metrics`, `tailscaled`, `sshd`, `docker` | standard | 9109 | — |

Not here: DefenseClaw (nothing installed), Cisco AIBOM (not enabled), the backup timer (not installed at check time).
OpenBot was planned here (D13) and waits on decision 0004.

## Never sleep (role `always_on`)

Applied by `playbooks/always-on.yml` (inventory group `always_on`; also imported by `site.yml`).

- `/etc/systemd/logind.conf.d/50-always-on.conf`: lid, suspend and hibernate keys and idle are ignored.
- `sleep.target`, `suspend.target`, `hibernate.target`, `hybrid-sleep.target` are masked, so `systemctl suspend` is refused.
- Any hypridle listener that suspends is commented out (Omarchy's own idle service only blanks and locks).
- Battery charge stop at 80% where the firmware allows it. The Inspiron answers EIO, so it is skipped there.
- `playbooks/alerting.yml` enables `docker.service` (Arch enables only `docker.socket`, which would not start the
  stack's containers after a boot).

## k3s

Agent node, label `nghodki.ai/role=agent-node`, `nghodki.ai/hw=x86`. ufw is on (and has a `limit` rule on 22/tcp; the
`hardening` role allows dgx-1's LAN and Tailscale addresses above it so Ansible and agents aren't rate-limited): the role opens 10250/tcp and 8472/udp
from 192.168.86.0/24 and 10.100.136.0/24, and allows pod traffic on `cni0` and `flannel.1`. /32 routes to
10.100.136.1 and .2 via the Sparks' LAN IPs live on the NetworkManager connection `nikghodki_wifi`. Kubelet:
`system-reserved=cpu=1,memory=2Gi`, `kube-reserved=cpu=250m,memory=512Mi`. If the Dell goes down, its pods are evicted
after 5 minutes.

## Operate

```bash
ssh nikghodki@192.168.86.49                    # from dgx-1
sudo docker ps
sudo tailscale serve status
ssh -L 8082:127.0.0.1:8082 nikghodki@192.168.86.49   # Gatus UI without Pocket ID (break-glass)
```

## Gotchas

- `docker` needs `sudo` for `nikghodki`.
- Decision 0009: the Dell can't be a "services box" (8 GB max, 2 cores, HDD, Wi-Fi). It hosts only small, stateless
  things plus the alerting path.
- When the Dell is down, Gatus and ntfy are gone. dgx-2 notices after 15 minutes and posts to the ntfy.sh backup topic
  (see [Alert delivery](../observability/alert-delivery.md)).
