# ops_agent_access

Read-only SSH access for the ambient ops agent (decision 0013, design §5.1 and Appendix B). How to use, rotate and
revoke: [runbooks/ops-agent.md](../../../runbooks/ops-agent.md#host-access-opsro).

- User `opsro` (system, home `/var/lib/opsro`, password locked, shell `/bin/sh` because sshd runs the forced command
  through it); groups: `opsro`, `systemd-journal`. The role refuses docker/sudo/wheel/adm.
- `authorized_keys` (root-owned): one ed25519 key with `restrict,command="/usr/local/sbin/ops-ro",from="..."`.
- `/usr/local/sbin/ops-ro` (`files/ops-ro.py`): the allowlist dispatcher. `/usr/local/libexec/ops-ro-root`
  (`files/ops-ro-root.py`): the root helper, the only command in `/etc/sudoers.d/ops-ro` (checked with `visudo -cf`).
- `/run/ops-ro` (tmpfiles.d) holds the rate-limit counter; `/etc/ops-agent/{certs,defenseclaw}` the per-host lists.
- The role asserts that sshd (`sshd -T -C user=opsro,...`) has no AllowUsers/AllowGroups/DenyUsers that would leave
  `opsro` out. None of the five hosts has such a list today, so `roles/hardening` is unchanged except the Dell's
  `hardening_ufw_ssh_allow`, which now also exempts dgx-2 from the UFW `LIMIT` on port 22.

Tests: `python -m pytest -q hosts/roles/ops_agent_access/files/tests` (CI unit-test job).

## Live test (2026-11-16, from dgx-1, with the SOPS key in a temporary folder)

Allowed verbs, exit code and output size (bytes):

| Verb | dgx-1 | dgx-2 | jetson | omarchy (Dell) | pi |
|---|---|---|---|---|---|
| `help` | 0 (968) | 0 (968) | 0 (968) | 0 (968) | 0 (968) |
| `health` | 0 (673) | 0 (570) | 0 (685) | 0 (869) | 0 (789) |
| `units` | 0 (4316) | 0 (3754) | 0 (4300) | 0 (2631) | 0 (2625) |
| `containers` | 0 (1168) | 0 (1347) | 0 (143) | 0 (296) | 0, "docker is not installed" |
| `journal ssh -1h` (`sshd` on the Dell) | 0 (64 KB, capped) | 0 (64 KB, capped) | 0 (64 KB, capped) | 0 (64 KB, capped) | 0 (64 KB, capped) |
| `gpu` | 0, nvidia-smi | 0, nvidia-smi | 0, sysfs | 0, "no nvidia-smi" | 0, "no nvidia-smi" |
| `certs` | 0, 11 certs | 0 | 0 | 0 | 0 |
| `defenseclaw` | 0, 1 gateway | 0, none listed | 0, 2 gateways | 0, none listed | 0, none listed |

Refused on every host (same result on all five):

| Attempt | Result |
|---|---|
| interactive shell (`ssh opsro@host`, no command) | exit 2 "refused: interactive sessions are not allowed"; with `-tt`: "PTY allocation request failed" |
| `env` | exit 2, unknown verb |
| `cat /etc/shadow` | exit 2, unknown verb |
| `status ssh; id` | exit 2, "usage: status <unit>" |
| `journal ssh -1h; rm -rf /` | exit 2, "usage: journal <unit> <since>" |
| `container-logs x --follow` | exit 2, "usage: container-logs <container>" |
| `reboot` | exit 2, unknown verb |
| `ssh -N -L 47124:127.0.0.1:22` (local forward) | channel refused: "open failed: administratively prohibited" |
| `ssh -N -R 47123:127.0.0.1:22` (remote forward) | exit 255, "remote port forwarding failed" |
| dgx-1 to dgx-2 over Tailscale (source 100.65.137.82, not in `from=`) | "Permission denied (publickey,password)" |
| 63 calls in a minute on the Pi | calls past 60 refused with exit 3, logged `refused=rate_limit` |
