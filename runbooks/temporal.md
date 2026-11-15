# Temporal (plan P4.7, interim before k3s)

Durable workflows for scheduled and long-running homelab jobs. For now it's a Docker stack on dgx-2; the k3s target is the
`jobs` namespace (architecture §"Namespaces"), with Postgres on CNPG.

| Piece | Where |
|---|---|
| Stack `jobs` | dgx-2 `/opt/homelab/jobs`, from `hosts/stacks/jobs`, deployed by `hosts/playbooks/jobs.yml` |
| Temporal server 1.32.2 (all four services in one container) | `temporal`; frontend gRPC on **192.168.86.36:7233** (LAN only) |
| PostgreSQL 17 | `postgresql`, volume `jobs_pg-data`; databases `temporal` and `temporal_visibility`; not published |
| admin-tools 1.32.2 | `admin-tools`: creates/upgrades the schemas on start, then idles for the `temporal` CLI |
| Web UI 2.58.1 | `ui`, 192.168.86.36:8233 (LAN), served as **https://temporal.nghodki.ai** by dgx-1's Caddy |
| Metrics | Prometheus endpoint on 192.168.86.36:9233, scraped by VictoriaMetrics (job `temporal`) |
| Uptime | Gatus group `jobs`: frontend TCP 7233 and `temporal.nghodki.ai/healthz` through the front door |
| Secrets | `secrets/jobs.enc.yaml` (`postgres_password`); `secrets/console.enc.yaml` (`oidc_temporal_secret`) |

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

## Workers

Workers (Omarchy, the Sparks) connect to `192.168.86.36:7233`, namespace `homelab`, plain gRPC:

```python
client = await temporalio.client.Client.connect("192.168.86.36:7233", namespace="homelab")
```

There's **no mTLS and no authorization** on the frontend yet: anyone on the LAN can start or terminate workflows. That's
why it's published on the LAN address only. **Add mTLS (and a claim mapper) before exposing it on Tailscale** or moving it
off the LAN.

## CLI

```bash
ssh nikghodki-dgx-2@192.168.86.36
cd /opt/homelab/jobs
sudo docker compose exec admin-tools temporal operator namespace list
sudo docker compose exec admin-tools temporal workflow list --namespace homelab
sudo docker compose exec admin-tools temporal operator cluster health
```

## Troubleshooting

- `temporal` won't start: it waits for `admin-tools` to be healthy, which waits for the schemas. Check
  `sudo docker compose logs admin-tools postgresql`.
- UI login loop or "returnUrl not in allowed origins": `TEMPORAL_CORS_ORIGINS` must be `https://temporal.nghodki.ai` and the
  Pocket ID callback `https://temporal.nghodki.ai/auth/sso/callback`.
- Metrics missing: `curl -s http://192.168.86.36:9233/metrics | head` on dgx-2, and `up{job="temporal"}` in Grafana.

## Backups

None: backups are off by [decision 0002](../decisions/0002-backups-off-for-now.md). Losing dgx-2's disk loses workflow
history and the namespace (recreate it with the playbook). Workflows should be safe to restart from scratch until then.
