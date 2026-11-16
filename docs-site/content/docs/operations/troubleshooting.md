---
title: Troubleshooting FAQ
description: Real problems hit while building the fleet, with their symptoms, causes and fixes.
---

## DNS and names

**kubectl or Argo CD says "no such host" for a `*.nghodki.ai` name that `dig` resolves.**
edge-dnsmasq answers AAAA with NXDOMAIN; Go's resolver treats that as "no such host". Since the P3.3 cutover clients
and pods get edge-dns in k3s, which answers AAAA with empty NOERROR; only queries that still reach dnsmasq
(192.168.86.44:53) hit this. ([DNS](../network/dns.md))

**`pi.nghodki.ai` goes nowhere.** It still points at 192.168.86.34; the Pi is .39. Use the IP or fix the line in
`cluster/platform/edge/names.txt`.

## Docker and Ansible

**A container that publishes on `192.168.86.x:port` is down after a reboot.** Docker tried to bind the LAN IP before
Wi-Fi was up ("cannot assign requested address", unverified exact message). Fix: `sudo docker compose --project-directory /opt/homelab/<stack> up -d`.
k3s isn't affected (it binds wildcard addresses).

**A service I added in a PR disappeared after someone else's deploy.** `compose_stack` uses `remove_orphans: true`; they
deployed the stack from a branch without your change. Rebase on `origin/main` before deploying shared stacks.

**I changed a config file but the service didn't pick it up.** Single-file bind mounts keep the old inode. The role
restarts services whose sub-folder changed; if you changed something by hand, restart the service yourself.

**The bus deploy failed on an empty `.env`.** Fixed in PR #16: `.env` is written only when the stack has variables.

**ansible-lint fails with `name[template]`.** Jinja in a task name must be at the end: `"Look up the namespace, {{ jobs_namespace }}"`,
not `"Look up {{ jobs_namespace }} namespace"`.

**Check mode fails on a new host for the OTel collector or a stack.** A first install can't be simulated; the roles print
"would install/deploy" instead. Run for real once.

**Tailscale install fails on Omarchy.** It needed a full system update first (PR #7, P0.10).

**ssh in a heredoc or loop eats the rest of my script.** Use `ssh -n` (no stdin).

**SSH from dgx-1 to the Dell is refused after a burst of connections.** UFW's `limit` rule on 22/tcp (6 new
connections per 30 s). The `hardening` role adds allow rules for dgx-1 above it; check `sudo ufw status numbered` and
re-run `playbooks/hardening.yml --limit omarchy`. The kernel log shows `[UFW LIMIT BLOCK]`.

## k3s

**`kubectl` says permission denied on `/etc/rancher/k3s/k3s.yaml`.** k3s's bundled `kubectl` defaults to the root-only
kubeconfig. `export KUBECONFIG=$HOME/.kube/config` (the profile script only does this in login shells).

**Labels or taints in `host_vars` didn't apply.** They only apply when a node registers. Use `kubectl label` /
`kubectl taint` too.

**The Jetson keeps going NotReady.** Wi-Fi drops (`journalctl -u NetworkManager`), or memory pressure
(`journalctl -k | grep -i oom`, the `MemoryPressure` condition).

**A pod or Deployment is refused by Kyverno.** The error names the policy. Typical: a third-party image without a
digest (`require-image-digest`), `:latest`, no requests/limits, an unlisted registry. Fix the manifest; check it with
`kyverno apply policies/kyverno --resource <dir>` before the PR ([Kyverno](../platform/kyverno.md)).

**Every `ghcr.io/nikghodki` image is refused with `UNAUTHORIZED`.** The GHCR packages are still private. Make them
public (GitHub UI) or add a pull Secret.

**`failed calling webhook ... kyverno-svc` and nothing new starts.** Both Kyverno admission replicas are down. Break-glass
B: stop selfHeal on `root` and `kyverno`, scale the admission controller to 0 first, then delete leftover webhooks.

## DefenseClaw

**Every skill got quarantined with "scanner failure (fail-closed) ... skill-scanner: executable file not found".** The
gateway's user unit has no `~/.local/bin` on PATH. Apply `playbooks/defenseclaw.yml` (role `defenseclaw_gateway_env`),
restart the gateway as the user, then `skill restore` + `skill unblock` (or copy back from quarantine). ([DefenseClaw](../security/defenseclaw.md))

**Edge policy push returns `HTTP 500 compile/sign failed: trusted policy compiler Python interpreter unavailable`.**
The gateway refuses a group-writable interpreter. dgx-1's umask is 002 and uv's Python inherits it:
`chmod -R go-w ~/.local/share/uv ~/.defenseclaw/.venv ~/.defenseclaw/installer`. Check again after uv installs a new Python.

**The Fleet gateway won't talk to NATS's MQTT.** It's MQTT 5 only; NATS is 3.1.1. That's why Fleet has its own Mosquitto.

**A second Hermes profile stopped the DefenseClaw gateway from starting.** One `HERMES_HOME` per account: run each profile
as its own Linux user.

**`defenseclaw policy edit scanner -p` broke the policy test.** It writes lowercase severity keys. Edit the YAML by hand.

**Every escalated tool call from the Pi is denied.** The OSS Fleet gateway is default-deny with no allow API. Known
limit; picoclaw stays on its in-process hook.

**The Edge Connector build fails on the Pi with deprecation errors.** mbedTLS 3.6 + `-Werror`: add
`-DCMAKE_C_FLAGS=-Wno-error=deprecated-declarations`.

**A device shows `degraded`.** Normal until its first Fleet verdict sets its clock.

**`defenseclaw mcp set` says `blocked [hermes]: mcp '<name>' is not in the approved registry`.** By design (P4.3): add the
server to `policies/defenseclaw/mcp-servers.yaml` with the same launch and to `tools/`, merge, run
`playbooks/defenseclaw.yml --limit jetson`.

**The MCP drift check reports `unapproved` or a changed tool.** See runbooks/mcp-admission.md "When it reports drift";
treat a changed tool as possible poisoning until reviewed.

## Sign-in

**Gatus crashed at start.** Its own `security.oidc` panics when Pocket ID is unreachable. Gatus has no OIDC; the front door
(`edge-auth`) does the sign-in and `status-gate` lets only the door through to the UI.

**Phoenix says "authentication failed" after Pocket ID.** Request the `groups` scope
(`PHOENIX_OAUTH2_POCKETID_SCOPES: groups`).

**Temporal UI login loops, "returnUrl not in allowed origins".** `TEMPORAL_CORS_ORIGINS` and the callback must be the
`https://temporal.nghodki.ai` URLs.

**Pocket ID rejects a client without PKCE.** Gatus 5.38 and Temporal UI 2.58 don't send PKCE; their clients have
`pkce: false`. Everything else uses S256.

**A passkey prompt never appears.** Passkeys need HTTPS and a trusted cert: install the web CA from `http://ca.nghodki.ai`
and use `https://`.

## Robot

**`/scan` doesn't reach the Jetson.** The Pi must use Zenoh client mode (peer mode advertises localhost locators).
Check `~/.config/homelab-ros/zenoh.env` and the router.

**Every ROS node on the Pi aborts with `Invalid configuration file` / `RCLBadAlloc`.** RoboStack's rmw_zenoh 0.6.9 session
config has a key libzenohc 1.9.0 rejects; the role writes a filtered `zenoh-session.json5`.

**`safety-reset` as picoclaw or hermes is refused.** By design: only `operator` may reset (`Publish Violation` in the NATS
log).

**The governor restarts every 2 s.** The Zenoh router must be up at start; with no router the node exits and systemd retries.

## Observability

**The DefenseClaw overview shows one more firing alert than exists.** It counts the always-firing Watchdog.

**`ObservabilityComponentDown` fired for Gatus.** Gatus needs `metrics: true` (PR #11).

**No GPU memory in DCGM on the Sparks.** GB10 reports it as N/A; use fleet-metrics' memory panels.

**AIBOM job skipped images.** MemAvailable was under 20 GiB on a Spark (`aibom.skipped` in the journal). Expected.

**`docker save` fails on dgx-2 in the AIBOM job.** containerd image store; the job falls back to copying files out of a
created container.

## MLflow and sims

**A new MLflow image isn't used after a Dockerfile change.** Compose builds only when the tag is missing: bump the tag.

**A sim job died with no error.** `measure.sh`'s watchdog stops it when MemAvailable is under 8 GiB; check the log line.

**JAX grabbed most of the memory.** It preallocates 75% by default; the compose file sets `PREALLOCATE=false` and
`MEM_FRACTION=0.15`.
