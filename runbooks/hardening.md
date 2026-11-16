# Host hardening (Lynis remediation)

Weekly Lynis audits (role `lynis`, `hosts/playbooks/lynis.yml`, unit `lynis-audit.service`/`.timer`) send the
hardening index and warnings to Loki (journal tag `lynis`). This runbook covers what we changed after the
2026-11-15 audit, which findings are documented exceptions, and how to roll back.

Ansible: role `hardening` (`hosts/playbooks/hardening.yml`, also part of `site.yml` after `base`) and the lynis
role's custom profile `/etc/lynis/custom.prf` (vars `lynis_skip_tests`, `lynis_promisc_interfaces` in host_vars).

**Lynis version.** Since 2026-11-15 the Debian/Ubuntu hosts (dgx-1, dgx-2, Jetson, Pi) run the upstream release
(`lynis_version` 3.1.7; the distros ship 3.0.9 and 3.1.4), hash-locked (`lynis_tarball_sha256`, the SHA-256
cisofy.com publishes) in `/opt/lynis/<version>`, with `/usr/local/lynis`, `/usr/local/sbin/lynis` and
`/usr/local/etc/lynis/default.prf` pointing at it. The distro package is purged: it also shipped a daily
`lynis.timer` that ran next to our weekly `lynis-audit.timer`. The Dell (Arch) keeps its package, which is current.
To upgrade, set `lynis_version` and `lynis_tarball_sha256` together and run `playbooks/lynis.yml`. The first 3.1.7
audit on dgx-2: hardening index 72 (68 with 3.0.9), 0 warnings.

**Retired units.** Units that were running but unused are stopped and disabled (not removed) by role
`retired_units` (`playbooks/retired.yml`; `retired_units_system` / `retired_units_user` in host_vars, each with its
reason). dgx-1: the NFS server (`nfs-server`, `nfs-blkmap`, `fsidd`, `rpcbind`; installed with the Jetson reflash
tools on 2026-11-12, `/etc/exports` empty, no clients) and `iperf3` (a one-off link test, it never accepted a
connection). Re-enable `nfs-server` and `rpcbind.socket` for the next Jetson reflash, and run `iperf3 -s` by hand for
a link test. dgx-2: `iperf3` (2026-11-16; enabled since the install, never accepted a connection). The Pi: the user
unit `dclaw-tunnel` (P1.12).

## Results (2026-11-15)

| Host | OS | Index before | Warnings before | Index after | Warnings after |
|---|---|---|---|---|---|
| dgx-1 | Ubuntu 24.04 (DGX OS) | 61 | 0 | 66 | 0 |
| dgx-2 | Ubuntu 24.04 (DGX OS) | 63 | 1 (PKGS-7392) | 68 | 0 |
| jetson | Ubuntu 24.04 (L4T / JetPack 7) | 59 | 5 | 65 | 2 (KRNL-5830, PKGS-7392; see below) |
| omarchy (Dell) | Arch (Omarchy) | 68 | 0 | 72 | 0 |
| pi | Debian 13 | 64 | 1 (PKGS-7388) | 70 | 0 |

## Warnings and what we did

| Host | Test | Cause | Action |
|---|---|---|---|
| dgx-2 | PKGS-7392 vulnerable packages | 6 ESM-apps security updates pending (freerdp2 libs, python3-pip, python3-wheel). On the Sparks `99update-notifier-nvidia` sets `APT::Periodic::Unattended-Upgrade "0"`, overriding `roles/base`, so unattended upgrades never run there. | Installed with the role's opt-in task (`--tags all,security_updates`: runs `unattended-upgrade` with the security-only origins and `NEEDRESTART_SUSPEND=1`, so no service restarts). Timer-driven upgrades on the Sparks stay off (see Skipped). |
| jetson | AUTH-9283 accounts without password | NVIDIA's `nvsciipc` and `nvsciipc2` system users (shell `/sbin/nologin`) had an empty shadow field. | Locked (`usermod -L`). The role locks any account with an empty password field that is a system account (UID < 1000 or nologin/false shell). |
| jetson | NETW-3015 promiscuous interface `usb0` | `usb0` is the L4T USB device-mode gadget, a port of bridge `l4tbr0`; bridge ports are promiscuous. | Exception: `if_promisc:usb0` in `host_vars/jetson.yml`. |
| jetson, pi | PKGS-7388 no security repository | False positive. The security suites are in deb822 `*.sources` files (`Suites: noble-security` / `trixie-security`), which Lynis' grep for `security.ubuntu.com` / `security/ ` does not match. | Exception: `skip-test=PKGS-7388` on those two hosts. The role asserts (`apt-cache policy`) that a `-security` suite is configured, so the skip can't hide a real gap. |
| jetson | KRNL-5830 reboot needed | This morning's unattended upgrade installed libc6 and gnome-shell. | **Not skipped, operator action**: reboot the Jetson in the monthly window. Clears itself after that. |
| jetson | PKGS-7392 vulnerable packages | `linux-firmware` is kept back: the security update splits it into new packages (`linux-firmware-amd-graphics`, ...), which unattended-upgrade won't install. | **Not skipped, operator action**: in the monthly window, `sudo apt-get install linux-firmware` then reboot. Not done now: it regenerates the initramfs on an L4T NVMe boot we can't reboot to verify. |

Transient warnings (reboot needed, pending updates) are not skipped: a skip would also hide the next real one.

## Changes (role `hardening`)

All Debian-family and Arch hosts unless noted.

- **sysctl** `/etc/sysctl.d/60-homelab-hardening.conf`: `fs.protected_{hardlinks,symlinks}=1`,
  `fs.protected_{fifos,regular}=2`, `fs.suid_dumpable=0`, `kernel.core_uses_pid=1`, `kernel.dmesg_restrict=1`,
  `kernel.kptr_restrict=1`, `dev.tty.ldisc_autoload=0`, `net.ipv4.tcp_syncookies=1`,
  `net.ipv{4,6}.conf.{all,default}.accept_redirects=0`, `net.ipv4.conf.{all,default}.accept_source_route=0`,
  `net.ipv4.conf.{all,default}.log_martians=1`, `kernel.yama.ptrace_scope=1` (only where Yama exists; not the Pi).
  Pi only (`hardening_router: false`, it doesn't forward): `net.ipv4.conf.{all,default}.send_redirects=0`.
  A task sets any running value that differs from the file (no `sysctl --system`, so nothing else is reloaded).
- **Never touched** (the role refuses these keys): `ip_forward`, `conf.*.forwarding`, `rp_filter` (dgx-1 stays
  loose, 2), `net.bridge.*`. Checked before and after: unchanged on every host.
- **Redirects on the k3s nodes**: with forwarding on, Linux accepts a redirect only if both `conf/all` and
  `conf/<if>` allow it, so `accept_redirects=0` is safe on routers. `send_redirects` is left on for the forwarding
  hosts (Sparks, Jetson, Dell), as the routers they are; turning it off would only stop the hint, not forwarding.
- **Setuid core dumps**: `fs.suid_dumpable=0`. `apport --start` (Ubuntu) sets it back to 2, so a drop-in
  `apport.service.d/50-homelab-suid-dumpable.conf` resets it after apport starts. On Arch, systemd's
  `50-coredump.conf` sets 2 and our `60-` file wins.
- **Kernel modules**: `dccp`, `sctp`, `rds`, `tipc` blacklisted and `install ... /bin/false`
  (`/etc/modprobe.d/60-homelab-hardening.conf`). None was loaded; flannel, Docker and Tailscale don't use them.
- **SSH** drop-in `/etc/ssh/sshd_config.d/55-homelab-hardening.conf` (after base's `50-homelab.conf`):
  `LogLevel VERBOSE` (logs the key fingerprint of each login) and `MaxStartups 30:50:100` (agents on dgx-1
  open many parallel short sessions). Base already has `PermitRootLogin no`, `X11Forwarding no`, `MaxAuthTries 4`.
- **Permissions**: `/etc/crontab` 0600, `/etc/cron.{d,hourly,daily,weekly,monthly}` 0700, `/etc/ssh/sshd_config`
  0600, `/etc/cups/cupsd.conf` 0640 (where they exist). cron and sshd run as root.
- **login.defs**: `SHA_CRYPT_MIN_ROUNDS`/`SHA_CRYPT_MAX_ROUNDS` 65536 and `YESCRYPT_COST_FACTOR` 7. Only
  affects passwords set later with `chpasswd`/`newusers`; nothing is re-hashed.
- **Banner** in `/etc/issue` (and `/etc/issue.net` on Debian/Ubuntu). Not an SSH `Banner`, so SSH output for
  scripts is unchanged. On Debian/Ubuntu these are `base-files` conffiles; unattended-upgrades keeps ours.
- **Packages** (Debian family): `debsums`, `apt-show-versions` (no services). Installed with
  `NEEDRESTART_SUSPEND=1`.
- **Dell UFW**: UFW's `limit` rule on 22/tcp (6 new connections per 30 s per source, then REJECT) blocked dgx-1's
  agents on 2026-11-15 (kernel log `[UFW LIMIT BLOCK] SRC=192.168.86.44 DPT=22`). With the user's approval the role
  inserts `allow 22/tcp from 192.168.86.44` and `from 100.65.137.82` (dgx-1 LAN and Tailscale, comment
  `dgx-1 automation`) **above** the limit rule (`hardening_ufw_ssh_allow` in `host_vars/omarchy.yml`). The limit
  rule and all UFW defaults stay as they were. Check: `sudo ufw status numbered`; 15 quick SSH connections from
  dgx-1 all succeed.

## Suggestions skipped on purpose

| Suggestion | Why not |
|---|---|
| SSH `AllowTcpForwarding no`, `AllowAgentForwarding no`, `MaxSessions 2`, `TCPKeepAlive no`, `MaxAuthTries 3`, non-22 port | The laptop's tunnels need TCP forwarding; agents and Ansible multiplex sessions; agents offer several keys. Would risk lockouts. |
| fail2ban (DEB-0880), any new SSH rate limits | Agents on dgx-1 open many short sessions; a ban would cut off automation. |
| Unattended upgrades on the Sparks (re-enable the timer) | NVIDIA turns them off; Ubuntu's needrestart can restart Docker/containerd/k3s/model serving after a library update. Apply with `--tags all,security_updates` instead. |
| `UMASK 027`, password ageing (AUTH-9328/9286), home dirs 0750 on the Pi (HOME-9304) | Containers running as other UIDs read files users create (bind mounts); ageing would expire key-only admin accounts' passwords for sudo. |
| `kernel.kptr_restrict=2`, `net.core.bpf_jit_harden=2`, `kernel.sysrq=0`, `kernel.modules_disabled=1`, `perf_event_paranoid` | Break perf/bpftrace symbols or BPF, remove emergency SysRq on the Dell (LUKS, never reboots), or stop k3s/Docker loading modules. |
| `send_redirects=0` on forwarding hosts | Brief: only on non-routers. Safe in theory, not needed. |
| USB/firewire storage drivers off (USB-1000, STRG-1846) | USB storage is used for flashing and recovery. |
| Compiler hardening (HRDN-7222) | The Pi builds the Edge Connector and the ROS driver; the Sparks build software too. |
| GRUB password, separate partitions, auditd rules, process accounting, AIDE, malware scanner, libpam-tmpdir, apt-listbugs/listchanges, needrestart (Pi/Jetson), purging rc packages | Reboot-path or partitioning risk, extra daemons with little value here, or apt prompts and auto-restarts. |

## Roll back

Everything is in drop-in files, so roll back by removing them:

```sh
sudo rm /etc/sysctl.d/60-homelab-hardening.conf /etc/modprobe.d/60-homelab-hardening.conf \
        /etc/ssh/sshd_config.d/55-homelab-hardening.conf
sudo rm -r /etc/systemd/system/apport.service.d && sudo systemctl daemon-reload   # Ubuntu
sudo systemctl reload ssh          # sshd on Arch
# Running sysctl values: set back by hand (sysctl -w key=old) or they revert at the next boot.
# Old defaults were: fs.protected_fifos=1, fs.suid_dumpable=2 (apport/systemd-coredump),
# accept_redirects=1 / log_martians=0 / default.accept_source_route=1 on the forwarding hosts.
sudo chmod 0644 /etc/crontab /etc/ssh/sshd_config; sudo chmod 0755 /etc/cron.*  # optional
# Dell only: remove the dgx-1 allow rules (the limit rule is untouched)
sudo ufw delete allow from 192.168.86.44 to any port 22 proto tcp
sudo ufw delete allow from 100.65.137.82 to any port 22 proto tcp
```

Then remove `role: hardening` from `hosts/playbooks/site.yml` so the next run doesn't put it back. Lynis
exceptions: empty `lynis_skip_tests`/`lynis_promisc_interfaces` in host_vars and run `playbooks/lynis.yml`.
Locked accounts: `sudo usermod -U nvsciipc` (but that restores an empty password).

## Run it

```sh
cd <worktree>/hosts && source ~/.venvs/ansible/bin/activate
ansible-playbook playbooks/hardening.yml --check --diff
ansible-playbook playbooks/hardening.yml --limit dgx-2      # one host first, then check SSH, k3s, Gatus
ansible-playbook playbooks/hardening.yml                    # the rest; a second run must show changed=0
ansible-playbook playbooks/hardening.yml --limit <host> --tags all,security_updates   # pending security updates
ansible all -b -m systemd_service -a "name=lynis-audit.service state=started"        # re-audit
```
