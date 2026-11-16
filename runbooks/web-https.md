# HTTPS for *.nghodki.ai (decision D25)

`nghodki.ai` isn't a registered public domain; only the home DNS (edge-dnsmasq) resolves it. So no public CA
can issue for it, and the sites use the **homelab web CA** instead:

| File | What |
|---|---|
| `hosts/files/pki/web-ca.crt` | Web CA, ECDSA P-256, 10 years, **name-constrained to `nghodki.ai`** (critical), `pathlen:0`. Even if its key leaked, it couldn't vouch for any other site |
| `hosts/files/pki/web.crt` | `nghodki.ai` + `*.nghodki.ai`, 397 days |
| `secrets/pki.enc.yaml` | `pki_web_ca_key`, `pki_web_key` |
| `hosts/files/web-ca/` | Install page served at `ca.nghodki.ai`: the `.crt`, an iOS/iPadOS `.mobileconfig`, instructions |

This is separate from the internal homelab CA (`homelab-ca.crt`, used for NATS, Fleet and backups and trusted by the fleet
hosts). That CA has no name constraint, so it must never be installed on phones or family devices.

## Devices

- Fleet hosts (dgx-1, dgx-2, Jetson, Omarchy, Pi): role `homelab_ca` (`playbooks/pki.yml`) installs both CAs in the system
  store. On Omarchy, browsers pick it up through p11-kit.
- Phones, Macs and Windows PCs: install it once from `http://ca.nghodki.ai`. Never install the internal homelab CA on them.

## Front door (dgx-1 `~/edge-gateway`, not in this repo)

Since P3.3 the clients use the in-cluster door (Caddy and CoreDNS in `edge`, same routes, same cert as the Secret
`edge/web-tls`; [edge.md](edge.md)); edge-caddy below remains as the relay to nginx-gateway and the rollback.

- `conf/Caddyfile`: every route lives in the `(nghodki_routes)` snippet, imported by `:80` and by `:443`
  (`tls /etc/caddy/certs/web.crt /etc/caddy/certs/web.key`). `voice-agent.nghodki.ai` uses the same cert.
  There's no :80 → :443 redirect yet, so devices without the CA keep working over http.
- `conf/certs/web.{crt,key}` (key 0600, from SOPS). `conf/ca/` is a copy of `hosts/files/web-ca/`.
- `dnsmasq/dnsmasq.conf`: `ca.nghodki.ai` → dgx-1.
- `@id` (Pocket ID, dgx-2 `192.168.86.36:1411`) and `@ops` (Homepage behind oauth2-proxy, on the Dell `192.168.86.49:4180`)
  redirect http → https:
  passkeys need HTTPS and oauth2-proxy's cookie is `Secure`. `ops.nghodki.ai` is in dnsmasq for the LAN and the tailnet.
- `@status` (Gatus) and `@ntfy` go to the Dell too: `192.168.86.49:8081` and `192.168.86.49:8085` (`flush_interval -1`
  so ntfy's streams aren't buffered). The phone doesn't use `ntfy.nghodki.ai`: it reaches ntfy on the Dell over Tailscale
  HTTPS, which needs neither the front door nor dgx-1's DNS ([alerting.md](alerting.md)).
- Apply changes with `docker restart edge-caddy` (`caddy reload` hasn't always taken effect).

## Renew (before December 2027; Gatus alerts 30 days ahead)

Re-issue `web.crt` with the same extensions (SAN `nghodki.ai`, `*.nghodki.ai`; EKU serverAuth; keyUsage
digitalSignature; AKI/SKI) from `pki_web_ca_key`, commit the cert, and copy the cert and key into `conf/certs/`.
Then restart edge-caddy, and refresh `cluster/platform/edge/web-tls.enc.yaml` for the in-cluster Caddy
([edge.md](edge.md) "Renew"). Devices don't need anything: they trust the CA, not the certificate.

## Later

- Once your devices trust the CA, add the :80 → :443 redirect and HSTS (short max-age first).
- If you ever register `nghodki.ai`, switch to Let's Encrypt via DNS-01 and retire this CA.
