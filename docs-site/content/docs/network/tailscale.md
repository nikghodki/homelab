---
title: "Tailscale"
description: "The tailnet: device tags, every grant in policies/tailscale/policy.hujson, split DNS for nghodki.ai, and Tailscale HTTPS on the Dell."
---

Tailscale gives remote access (phone, admin devices, family) and a second path between fleet hosts. The access policy
is in Git: `policies/tailscale/policy.hujson`. It governs Tailscale traffic only; LAN traffic between the devices is
not affected by it.

## Devices and tags

Fleet devices are **tagged devices**: owned by a tag, not a person, so their keys don't expire.

| Device (MagicDNS) | Tailscale IP | Tags |
|---|---|---|
| `spark-83dc` (dgx-1) | 100.65.137.82 | `tag:gpu`, `tag:control` |
| `nikghodki-dgx-2` | 100.124.175.23 | `tag:gpu`, `tag:control` |
| `nikhil-jetson` | 100.78.145.123 | `tag:control`, `tag:home`, `tag:agent` |
| `nikghodki-omarchy-1` (Dell) | 100.117.118.69 | `tag:agent` |
| `nikghodki-raspberry` | 100.64.25.22 | `tag:robot` |

`tag:quarantine` exists for incidents: reachable only by admins, reaches nothing. All tags are owned by
`group:admins`. Personal devices (phone, Macs) belong to their users and are not tagged.

The policy names two hosts by IP: `dgx-1` = 100.65.137.82 and `dgx-2` = 100.124.175.23.

## Groups

| Group | Members |
|---|---|
| `group:admins` | `nikghodki@gmail.com` (the admin identity) |
| `group:family` | one family account (see the file) |
| `group:guests` | one guest account (see the file) |

## Grants, one by one

| # | From | To | Ports | Why |
|---|---|---|---|---|
| 1 | `group:admins` | everything | all | You: SSH, kubectl, every UI |
| 2 | `group:family`, `group:guests` | dgx-1, dgx-2 | tcp 80, 443, tcp/udp 53 | The web front door (Home Assistant, Open WebUI, …) and DNS for `nghodki.ai`, on both Sparks for the in-cluster front door (#78) |
| 3 | `tag:gpu`, `tag:control` | `tag:gpu`, `tag:control` | all | Sparks and the Jetson talk freely (k3s, etcd, NATS, model sync) |
| 4 | every fleet tag | dgx-1, dgx-2 | tcp/udp 53, tcp 80, 443 | DNS and the front door for fleet devices (dgx-2 added in #78) |
| 5 | every fleet tag | dgx-2 | tcp 4317–4320, 8000 | OTLP telemetry and backups |
| 6 | `tag:agent`, `tag:home` | dgx-1 | tcp 4000, 4222, 8883 | LiteLLM, NATS, MQTT |
| 7 | `tag:robot` | dgx-1 | tcp 8883, 4222, 8884 | MQTT/NATS and the DefenseClaw Fleet broker (D24) |
| 8 | dgx-1 | every fleet tag | tcp 22 | Ansible and admin automation from dgx-1 |
| 9 | dgx-1 | `tag:agent` | tcp 443 | dgx-1 checks the Dell's ntfy over Tailscale HTTPS (PR #56) |

Grants 2 and 4 gained dgx-2 in #78, step 1 of the P3.3 cutover (`runbooks/edge.md`): the front door and DNS answer on
both Sparks' Tailscale IPs. That the console policy matches the file is unverified (the cutover needed it).

SSH rule: `group:admins` may use Tailscale SSH to their own devices (`autogroup:self`) as non-root or root, with
`check` (re-authentication).

What is **not** granted, on purpose: `tag:robot` can't reach LiteLLM (4000), SSH, or the Fleet API (8971); no tag can
reach Grafana (3000) or Temporal (7233) on dgx-2 over Tailscale; dgx-2 has no Tailscale path to the Dell at all.

## Tests in the policy

Tailscale runs these on every save and refuses a policy that breaks one:

| Source | Must accept | Must deny |
|---|---|---|
| the admin | dgx-2:22, dgx-1:4000 | — |
| the family account | dgx-1:443, dgx-1:80, dgx-2:443, dgx-2:53 | dgx-1:22, dgx-2:22, dgx-2:3000, dgx-1:5432 |
| the guest account | dgx-1:443, dgx-2:443 | dgx-1:22, dgx-1:8883, dgx-2:22, dgx-2:6006 |
| `tag:robot` | dgx-1:8883, dgx-1:8884, dgx-2:4319 | dgx-1:4000, dgx-1:22, dgx-1:8971, dgx-2:3000 |
| `tag:agent` | dgx-1:4000, dgx-1:8883 | dgx-2:22 |
| dgx-1 | `tag:agent`:443, `tag:robot`:22 | `tag:robot`:443 |

Checked live from the Pi (P1.4): bus and Fleet broker open; LiteLLM, SSH and the Fleet API blocked.

## Split DNS

The tailnet's DNS settings (admin console, not in the repo) send `nghodki.ai`, and a separate `model.nghodki.ai`
entry, to **both Sparks' Tailscale IPs**, 100.65.137.82 and 100.124.175.23 (`tailscale dns status` on dgx-1, after the
P3.3 cutover on 2026-11-15). On both, the in-cluster edge-dns answers ([DNS](dns.md)); each replica answers with its
own Spark's Tailscale IP, so a client never gets a dead Spark's address for longer than the 30 s TTL.

Before the cutover only 100.65.137.82 was listed, where edge-dnsmasq answered with both of dgx-1's addresses.
Rollback for a broken dgx-2 or cluster: remove 100.124.175.23 from the nameservers (`runbooks/edge.md`).

## Tailscale HTTPS

Only one service uses Tailscale's own HTTPS (a Let's Encrypt cert for the node's `ts.net` name, managed by tailscaled):
ntfy on the Dell, `https://nikghodki-omarchy-1.tail1cb707.ts.net` → `127.0.0.1:8085` (role `tailscale_serve`,
`playbooks/alerting.yml`). The phone's ntfy app subscribes there, so it works without dgx-1. Everything else uses the
homelab web CA (D25), because `ts.net` names were rejected for the web front door (2026-11-15).

## Change the policy

1. Edit `policies/tailscale/policy.hujson` in a PR; add a test for the new rule.
2. After merge, paste the file into the Tailscale admin console (Access controls). The tests must pass.
3. To add a new tag: first add only its `tagOwners` entry to the live policy and save, then tag the device, then apply
   the full file (a tag can't be applied before the live policy defines its owner).
4. From a family device, check that Home Assistant and Open WebUI still open.

Later (plan): apply from CI with Tailscale's GitOps action.

## Gotchas

- `docs/architecture.md` §4.2 mentions `tag:admin` for the work Mac. The live policy has no `tag:admin`; admins are
  `group:admins` (people's devices).
- Family and guests can reach every front-door route, including `litellm-admin.nghodki.ai` and `coolify.nghodki.ai`;
  those apps' own logins are the only gate (see [Front door](front-door.md)).
