# Temporal (plan P4.7, interim before k3s)

Durable workflows for scheduled and long-running homelab jobs. For now it's a Docker stack on dgx-2; the k3s target is the
`jobs` namespace (architecture §"Namespaces"), with Postgres on CNPG.

| Piece | Where |
|---|---|
| Stack `jobs` | dgx-2 `/opt/homelab/jobs`, from `hosts/stacks/jobs`, deployed by `hosts/playbooks/jobs.yml` |
| Temporal server 1.32.2 (all four services in one container) | `temporal`; frontend gRPC on **192.168.86.36:7233** (LAN only, **mTLS required**). Image `homelab/temporal-server:1.32.2-homelab.1`, built on dgx-2 from `temporal/build/` (upstream plus one claim mapper, below); config `temporal/config.yaml` |
| PostgreSQL 17 | `postgresql`, volume `jobs_pg-data`; databases `temporal` and `temporal_visibility`; not published |
| admin-tools 1.32.2 | `admin-tools`: creates/upgrades the schemas on start, then idles for the `temporal` CLI |
| Web UI 2.58.1 | `ui`, 192.168.86.36:8233 (LAN), served as **https://temporal.nghodki.ai** by dgx-1's Caddy |
| Metrics | Prometheus endpoint on 192.168.86.36:9233, scraped by VictoriaMetrics (job `temporal`) |
| Uptime | Gatus group `jobs`: frontend TCP 7233 and `temporal.nghodki.ai/healthz` through the front door |
| Secrets | `secrets/jobs.enc.yaml` (`postgres_password`); `secrets/console.enc.yaml` (`oidc_temporal_secret`); `secrets/pki.enc.yaml` (`pki_temporal_*_key`: the Temporal CA and every certificate key) |
| Certificates | `hosts/files/pki/temporal/` (public): `ca.crt`, `server.crt`, one `<client>.crt` per client; `issue.sh` makes new ones |

History shards are fixed at 4 for the life of the database.

## Deploy or change

```bash
source ~/.venvs/ansible/bin/activate && cd ~/homelab/hosts
ansible-playbook playbooks/jobs.yml --check --diff
ansible-playbook playbooks/jobs.yml
```

The playbook waits for the frontend and creates namespace `homelab` (retention 7 days) if it's missing. Upgrades: bump all
three Temporal images together (server and admin-tools share a version); admin-tools applies new schema versions before
the server starts.

## Sign-in

The UI uses its own OIDC login against Pocket ID (client `temporal`, group `admins`, no PKCE because the UI doesn't send it;
see [sign-in.md](sign-in.md)). Caddy redirects http to https because the UI's session cookies are Secure. Without a session
the UI's API answers 401. If Pocket ID is down at UI start, the UI exits and Docker restarts it until it can reach
`https://id.nghodki.ai`.

The front-door route (`@temporal` in `~/edge-gateway/conf/Caddyfile`) and the DNS entries (`temporal.nghodki.ai` →
192.168.86.44 and 100.65.137.82 in `~/edge-gateway/dnsmasq/dnsmasq.conf`) live on dgx-1, outside this repo.

## mTLS and authorization

Since 2026-11-16 (decision 0013, prerequisite of the ops agent) the frontend requires **mutual TLS**, and what a
client may do follows from its certificate:

- **Its own CA.** `homelab Temporal CA` (ECDSA P-256, 10 years, `pathlen:0`) signs the frontend's certificate and the
  client certificates (2 years). It's separate from the homelab CA and the web CA: only Temporal trusts it, so a key
  leaked elsewhere can't reach Temporal, and a Temporal client certificate is good for nothing else.
- **Roles in the certificate.** Each client certificate carries its Temporal roles as URI SANs,
  `urn:homelab:temporal:system:<reader|writer|admin>` or `urn:homelab:temporal:ns:<namespace>:<reader|writer|admin>`.
  Upstream Temporal maps roles only from JWTs, so the server is rebuilt with one small claim mapper
  (`hosts/stacks/jobs/temporal/build/tlsclaims.go`, ~70 lines, plus a 13-line patch to `cmd/server/main.go`; its unit
  test runs in the image build). Temporal's own **default authorizer** then enforces the roles. Bearer tokens (the UI
  forwards the user's Pocket ID token) are ignored.
- No certificate, a certificate from another CA, or plain gRPC: the TLS handshake fails. A valid certificate without a
  role for the namespace: `Request unauthorized` (only the health check is open).

| Client | Certificate | Roles |
|---|---|---|
| The server's own system worker (schedules, batch, per-namespace workers) | `system-worker.crt` | system admin |
| admin-tools (`temporal` CLI, the playbook's namespace tasks) | `admin-tools.crt` | system admin |
| Web UI (admins only, through Pocket ID) | `ui.crt` | system admin |
| Ops agent (`cluster/apps/ops`) | `ops-agent.crt` | writer on namespace `ops-agent` only |

Namespaces (created by the playbook if missing): `homelab` (7 days), `ops-agent` (30 days).

Checked on 2026-11-16 from dgx-1 with the admin-tools image: plain gRPC → "The server requires TLS"; TLS without a
certificate and with a self-signed `system:admin` certificate → "requires client certificates (mTLS)"; with
`ops-agent.crt`: health SERVING, start/list in `ops-agent` ok, list/start in `homelab`, list namespaces and delete its
own namespace → `Request unauthorized`.

**New client** (a worker on a Spark, say): `hosts/files/pki/temporal/issue.sh client <name> ns:homelab:writer` on
dgx-1 (with `~/.local/bin` on PATH for `sops`). It writes `<name>.crt` and stores the key in SOPS as
`pki_temporal_<name>_key`; commit both, then deliver the key like any other secret (a `*.key.j2` template, or a KSOPS
Secret in k3s). Renewal: run `issue.sh` again for the same name before the date in `openssl x509 -enddate`
(2028-11-15 for the current set) and redeploy; the server warns in its log 30 days ahead (`expirationChecks`).

## Workers

Workers connect to `192.168.86.36:7233` with a client certificate (Python SDK):

```python
from temporalio.client import Client, TLSConfig
tls = TLSConfig(server_root_ca_cert=open("ca.crt", "rb").read(), domain="temporal",
                client_cert=open("worker.crt", "rb").read(), client_private_key=open("worker.key", "rb").read())
client = await Client.connect("192.168.86.36:7233", namespace="homelab", tls=tls)
```

`domain="temporal"` is a name in the server certificate (`temporal`, `localhost`, `192.168.86.36`, `127.0.0.1`).
The frontend stays on the LAN address only.

## CLI

```bash
ssh nikghodki-dgx-2@192.168.86.36
cd /opt/homelab/jobs
# admin-tools carries the CLI's TLS settings in its environment (TEMPORAL_TLS_*), so no flags are needed
sudo docker compose exec admin-tools temporal operator namespace list
sudo docker compose exec admin-tools temporal workflow list --namespace homelab
sudo docker compose exec admin-tools temporal operator cluster health
```

## Troubleshooting

- `temporal` won't start: it waits for `admin-tools` to be healthy, which waits for the schemas. Check
  `sudo docker compose logs admin-tools postgresql`.
- UI login loop or "returnUrl not in allowed origins": `TEMPORAL_CORS_ORIGINS` must be `https://temporal.nghodki.ai` and the
  Pocket ID callback `https://temporal.nghodki.ai/auth/sso/callback`.
- A client gets `The server requires client certificates (mTLS)`: its certificate is missing, from another CA, or
  expired (`openssl x509 -in <crt> -noout -enddate -issuer`). `Request unauthorized`: the certificate has no role for
  that namespace (`openssl x509 -in <crt> -noout -ext subjectAltName`).
- The UI shows errors listing namespaces: `docker compose logs ui` (TLS), and that `ui/tls/ui.key` is 0600 for uid 1000.
- The `temporal` image won't build (compose builds it when the tag is missing): it clones `temporalio/temporal` at
  the pinned commit and downloads Go modules, so it needs the internet; the module layer retries 5 times.
- Metrics missing: `curl -s http://192.168.86.36:9233/metrics | head` on dgx-2, and `up{job="temporal"}` in Grafana.

## Backups

None: backups are off by [decision 0002](../decisions/0002-backups-off-for-now.md). Losing dgx-2's disk loses workflow
history and the namespace (recreate it with the playbook). Workflows should be safe to restart from scratch until then.
