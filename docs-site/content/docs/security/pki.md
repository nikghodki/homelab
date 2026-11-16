---
title: PKI (three CAs) and certificate renewal
description: The internal homelab CA, the name-constrained web CA and the Temporal CA, what each signs, who trusts which, and how to renew.
---

## The three CAs

| CA | File (public cert) | Private key (SOPS) | Constraint | Signs | Trusted by |
|---|---|---|---|---|---|
| **Internal homelab CA** | `hosts/files/pki/homelab-ca.crt` | `secrets/pki.enc.yaml` → `pki_homelab_ca_key` | none | NATS (`nats.crt`), the Fleet broker and API (`fleet.crt`), the backup server (`backup.crt`) | fleet hosts only (role `homelab_ca`). **Never** install it on phones or family devices |
| **Homelab web CA** (D25) | `hosts/files/pki/web-ca.crt` (same as `hosts/files/web-ca/nghodki-web-ca.crt`) | `secrets/pki.enc.yaml` → `pki_web_ca_key` | name-constrained to `nghodki.ai` (critical), `pathlen:0`, ECDSA P-256, 10 years | the `nghodki.ai` + `*.nghodki.ai` wildcard (`web.crt`, 397 days) | fleet hosts, plus phones and computers that installed it from `ca.nghodki.ai` |
| **Homelab Temporal CA** (2026-11-16, decision 0013) | `hosts/files/pki/temporal/ca.crt` | `secrets/pki.enc.yaml` → `pki_temporal_ca_key` | `pathlen:0`, ECDSA P-256, 10 years | Temporal's frontend certificate and its client certificates (roles as URI SANs) | Temporal's frontend (client CA) and its clients only; never a system store |

Leaf keys: `pki_nats_key`, `pki_fleet_key`, `pki_backup_key`, `pki_web_key`, all in `secrets/pki.enc.yaml`. They are
rendered into stacks by templates (`*.key.j2`) at deploy time.

Why separate CAs: the web CA can only vouch for `nghodki.ai` names, so even if its key leaked it couldn't impersonate any other
site. The internal CA has no constraint, so it stays on fleet hosts. The Temporal CA is trusted by Temporal alone, so its
client certificates can't authenticate anywhere else and other leaked keys can't reach Temporal. Issue and renew its
certificates with `hosts/files/pki/temporal/issue.sh` (`runbooks/temporal.md`).

## Where the certs are used

| Cert | Served by | Where it lives on the host |
|---|---|---|
| `web.crt` / key | edge-caddy on dgx-1 (`:443`); the in-cluster Caddy (P3.3) | `~/edge-gateway/conf/certs/`; KSOPS Secret `edge/web-tls` (`cluster/platform/edge/web-tls.enc.yaml`) |
| `nats.crt` | NATS on dgx-1 (4222, 8883) | `/opt/homelab/bus/nats/certs/` |
| `fleet.crt` | Mosquitto 8884 and fleet-caddy 8971 on dgx-1 | `/opt/homelab/fleet/{mosquitto,caddy}/certs/` |
| `backup.crt` | restic rest-server on the Jetson (re-issued 2026-11-16 for its names and addresses, same key; expires 2028-11-15) | `/opt/homelab/backup/rest-server/` |

Clients that verify the internal CA point at `/usr/local/share/ca-certificates/homelab-ca.crt` (Edge Connector, Fleet
gateway, safety governor, NATS clients). Containers that talk to Pocket ID mount the host bundle
`/etc/ssl/certs/ca-certificates.crt`, which includes the web CA. Argo CD carries the web CA inline as `rootCA` in its
OIDC config (`cluster/platform/argocd/values.yaml`). Gatus has neither CA, so its TLS checks use `insecure: true` and
only check expiry.

## Trust on fleet hosts (role `homelab_ca`)

`playbooks/pki.yml` copies both CAs into the system store: `/usr/local/share/ca-certificates/` + `update-ca-certificates`
on Debian/Ubuntu, `/etc/ca-certificates/trust-source/anchors/` + `trust extract-compat` on Arch (browsers on Omarchy pick
it up through p11-kit).

## Phones and laptops

Open `http://ca.nghodki.ai` (plain http on purpose; the device doesn't trust the CA yet). The page offers the `.crt`
and an iOS/iPadOS `.mobileconfig`. On iOS, also turn on full trust in Settings → General → About → Certificate Trust
Settings (standard iOS step; unverified wording in the page). Install only the **web** CA.

## Renewal

| Cert | Expires | Alert | How |
|---|---|---|---|
| `web.crt` | before December 2027 (397 days from 2026-11-15) | Gatus `*.nghodki.ai certificate` fails under 30 days | below |
| Fleet API cert | (unverified date) | Gatus `Fleet API` fails under 14 days (336 h) | re-issue `fleet.crt` from the internal CA, commit, `playbooks/fleet.yml` |
| k3s API serving cert | managed by k3s | Gatus `API dgx-1/dgx-2` fail under 30 days | k3s rotates its own certs on restart within 90 days of expiry |
| `nats.crt`, `backup.crt` | (unverified date) | none | re-issue, commit, `playbooks/bus.yml` / `backups.yml` |
| Temporal server and client certs | 2028-11-15 | Temporal logs a warning 30 days ahead | `hosts/files/pki/temporal/issue.sh server` / `client <name> <roles>`, commit, `playbooks/jobs.yml` (and the ops app's KSOPS Secret) |
| Web CA | 2036 | none | new CA = reinstall on every device |

Renew the web wildcard:

1. On dgx-1, with `pki_web_ca_key` from SOPS (never write it to disk unencrypted outside a temp dir you remove), issue a
   new `web.crt` with the same extensions: SAN `nghodki.ai`, `*.nghodki.ai`; EKU serverAuth; keyUsage
   digitalSignature; AKI/SKI.
2. Commit `hosts/files/pki/web.crt` (and `pki_web_key` in SOPS if the key changed).
3. Copy cert and key to `~/edge-gateway/conf/certs/` (key 0600) and `docker restart edge-caddy`.
4. Refresh `cluster/platform/edge/web-tls.enc.yaml` from SOPS (`runbooks/edge.md`, "Renew the wildcard cert"), merge,
   then `kubectl -n edge rollout restart deploy/edge-caddy` (the Secret's name doesn't change, so the pods don't roll
   on their own).
5. Devices need nothing: they trust the CA, not the certificate.

The exact `openssl` commands aren't in the repo (runbooks/web-https.md describes the extensions only).

## Later

- HTTP → HTTPS redirect and HSTS once devices trust the CA.
- If `nghodki.ai` is ever registered: Let's Encrypt via DNS-01, retire the web CA.
