---
title: Host hardening and Lynis
description: "The base and hardening roles (SSH, sysctl, modules, permissions, banner, UFW on the Dell), the weekly Lynis audit with its documented exceptions, what was skipped on purpose, and how to roll back."
---

Two Ansible roles harden every host, and a weekly Lynis audit measures the result. Runbook: runbooks/hardening.md
(PR #70).

## Base role (`hosts/roles/base`, first in `playbooks/site.yml`)

| Setting | Value | File on the host |
|---|---|---|
| Supported OS | Debian family or Arch (the role asserts this) | — |
| Time zone | America/Los_Angeles (`base_timezone`) | — |
| sshd drop-in | `PermitRootLogin no`, `X11Forwarding no`, `MaxAuthTries 4`; password auth stays **on** until every admin path has a key (`base_ssh_disable_password_auth: false`) | `/etc/ssh/sshd_config.d/50-homelab.conf`; `Include` added to the top of `sshd_config` (validated with `sshd -t`) |
| Journal cap | `SystemMaxUse` 1G (Jetson 500M, Pi 300M) | `/etc/systemd/journald.conf.d/50-homelab.conf` |
| Security-only upgrades (Debian/Ubuntu) | `unattended-upgrades` with `-security` origins only, no automatic reboot | `/etc/apt/apt.conf.d/52homelab-unattended-upgrades` |

**On the Sparks unattended upgrades never run**: NVIDIA's `99update-notifier-nvidia` sets
`APT::Periodic::Unattended-Upgrade "0"`, overriding the base role. That is kept on purpose (needrestart could restart
Docker, containerd, k3s or model serving); apply security updates there with the hardening role's opt-in tag (below).
Omarchy (Arch) gets no unattended upgrades; update it in the monthly window.

`site.yml` runs `base`, `hardening`, `tailscale` (installed, running, login state reported) and `fleet_metrics`, then
imports `always-on.yml`.

## Hardening role (`hosts/roles/hardening`, `playbooks/hardening.yml`, also in `site.yml` after `base`)

Low-risk changes from the Lynis suggestions; everything is a drop-in file, so it rolls back by deleting files.

| Area | What | Where |
|---|---|---|
| sysctl | `fs.protected_hardlinks/symlinks=1`, `fs.protected_fifos/regular=2`, `fs.suid_dumpable=0`, `kernel.core_uses_pid=1`, `kernel.dmesg_restrict=1`, `kernel.kptr_restrict=1`, `dev.tty.ldisc_autoload=0`, `net.ipv4.tcp_syncookies=1`, no ICMP redirects accepted, no source routing, log martians, `kernel.yama.ptrace_scope=1` (where Yama exists; not the Pi). Pi only (`hardening_router: false`): `send_redirects=0`. Running values are set to match without a full `sysctl --system` | `/etc/sysctl.d/60-homelab-hardening.conf` |
| Never touched | the role refuses `ip_forward`, `conf.*.forwarding`, `rp_filter` (dgx-1 stays loose, 2), `net.bridge.*`: k3s, flannel, Docker and Tailscale own them | — |
| Setuid core dumps | apport (Ubuntu) sets `suid_dumpable=2` at start; a drop-in resets it to 0 after apport | `apport.service.d/50-homelab-suid-dumpable.conf` |
| Kernel modules | `dccp`, `sctp`, `rds`, `tipc` blacklisted and `install ... /bin/false` | `/etc/modprobe.d/60-homelab-hardening.conf` |
| SSH | `LogLevel VERBOSE` (logs each login's key fingerprint), `MaxStartups 30:50:100` (agents on dgx-1 open many short sessions) | `/etc/ssh/sshd_config.d/55-homelab-hardening.conf` |
| Permissions | `/etc/crontab` 0600, `/etc/cron.*` 0700, `/etc/ssh/sshd_config` 0600, `/etc/cups/cupsd.conf` 0640 | — |
| login.defs | SHA-crypt rounds 65536, yescrypt cost 7 (only for passwords set later) | `/etc/login.defs` |
| Banner | "Authorised access only ..." in `/etc/issue` (and `issue.net` on Debian/Ubuntu); not an SSH banner, so script output is unchanged | — |
| Packages (Debian family) | `debsums`, `apt-show-versions` | — |
| Accounts | locks any system account with an empty password field (the Jetson's `nvsciipc`, `nvsciipc2`) | — |
| Dell UFW | inserts `allow 22/tcp from 192.168.86.44` and `from 100.65.137.82` (dgx-1, comment `dgx-1 automation`) **above** UFW's `limit` rule, which had blocked dgx-1's agents (`[UFW LIMIT BLOCK]`); the limit stays for everyone else (`hardening_ufw_ssh_allow` in `host_vars/omarchy.yml`) | `sudo ufw status numbered` |
| Security updates (opt-in) | `--tags all,security_updates` runs `unattended-upgrade` with the security origins and `NEEDRESTART_SUSPEND=1` (no service restarts) | — |

```bash
cd ~/homelab/hosts && source ~/.venvs/ansible/bin/activate
ansible-playbook playbooks/hardening.yml --check --diff
ansible-playbook playbooks/hardening.yml --limit dgx-2      # one host first; check SSH, k3s, Gatus
ansible-playbook playbooks/hardening.yml                    # the rest; a second run must show changed=0
ansible-playbook playbooks/hardening.yml --limit <host> --tags all,security_updates
```

## Lynis (`hosts/roles/lynis`, `playbooks/lynis.yml`)

- `lynis-audit.timer`: Sunday 03:30 + up to 30 min, `Persistent=true`. Service at `Nice=19`, idle CPU and I/O.
- `/usr/local/sbin/lynis-audit` runs `lynis audit system --quiet` and logs to the journal with tag `lynis`: one line
  `hardening_index=N warnings=W suggestions=S tests=T lynis=V exit=E` and one line per warning. Report in
  `/var/log/lynis-report.dat`. The host collector ships it to Loki; Fleet Home shows the latest index per host.
- Documented exceptions in `/etc/lynis/custom.prf` from `lynis_skip_tests` and `lynis_promisc_interfaces` in
  `host_vars`: the Jetson's `usb0` (L4T USB gadget, a bridge port, so promiscuous), and `PKGS-7388` on the Jetson and
  the Pi (a false positive: the security suites are in deb822 `*.sources` files; the role asserts a `-security` suite
  is configured, so the skip can't hide a real gap).
- Transient warnings (reboot needed, pending updates) are never skipped.

| Host | Index before → after (2026-11-15) | Warnings after |
|---|---|---|
| dgx-1 | 61 → 66 | 0 |
| dgx-2 | 63 → 68 | 0 (6 ESM security updates installed with the opt-in tag) |
| Jetson | 59 → 65 | 2, **operator actions**: KRNL-5830 reboot needed (libc6, gnome-shell); PKGS-7392 `linux-firmware` kept back (in the monthly window: `sudo apt-get install linux-firmware`, then reboot) |
| Dell | 68 → 72 | 0 |
| Pi | 64 → 70 | 0 |

Since 2026-11-15 the Debian/Ubuntu hosts run upstream Lynis 3.1.7 (`/opt/lynis`, hash-locked); the distro package
and its daily `lynis.timer` are gone, so only `lynis-audit.timer` runs (runbooks/hardening.md).

## Skipped on purpose

| Suggestion | Why not |
|---|---|
| SSH `AllowTcpForwarding no`, `AllowAgentForwarding no`, `MaxSessions 2`, `MaxAuthTries 3`, another port | the laptop's tunnels need forwarding; agents and Ansible multiplex; lockout risk |
| fail2ban, more SSH rate limits | agents on dgx-1 open many short sessions |
| unattended upgrades on the Sparks | needrestart could restart Docker/k3s/model serving; use the opt-in tag |
| `UMASK 027`, password ageing, home dirs 0750 on the Pi | containers running as other UIDs read bind-mounted files; ageing would expire key-only accounts' sudo passwords |
| `kptr_restrict=2`, `bpf_jit_harden=2`, `sysrq=0`, `modules_disabled=1`, `perf_event_paranoid` | break perf/BPF, remove SysRq on the Dell, or stop k3s/Docker loading modules |
| USB storage off, compiler hardening | USB is used for flashing; the Pi and Sparks build software |
| GRUB password, partitions, auditd, process accounting, AIDE, malware scanner, apt-listbugs, needrestart | reboot-path or partitioning risk, or extra daemons and prompts |

## Roll back

Delete `/etc/sysctl.d/60-homelab-hardening.conf`, `/etc/modprobe.d/60-homelab-hardening.conf`,
`/etc/ssh/sshd_config.d/55-homelab-hardening.conf` and the apport drop-in, reload sshd, set running sysctl values back by
hand (or reboot), delete the two UFW allow rules on the Dell, and remove `role: hardening` from `site.yml`. Exact
commands and the old defaults: runbooks/hardening.md.

## Other controls

| Control | Status |
|---|---|
| Kyverno in k3s | 6 policies in Enforce ([Kyverno](../platform/kyverno.md)) |
| Tetragon / DefenseClaw kernel controls | not installed (P3.6) |
| kube-bench | not set up |
| CrowdSec on the front door | not deployed |
| SSH password auth off | waiting (see above) |
| Memory guards on the Sparks | `earlyoom` and `gpu-oom-guard` run, but are not in the repo ([discrepancies](../decisions/discrepancies.md)) |
