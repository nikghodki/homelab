---
title: How to add things
description: Step-by-step recipes for adding a host, a service, a Pocket ID client, a DNS name, a Caddy route, a Gatus check, an alert, a NATS user, an MCP server and an Edge device.
---

Each recipe ends with a PR. Things outside the repo (DNS, Caddy) are changed by hand on dgx-1 and mentioned in the PR.

## A host

1. Fresh OS, a user with sudo, SSH key from dgx-1 (`ssh-copy-id`).
2. DHCP reservation on the Nest Wifi Pro.
3. Tailscale: join the tailnet, then tag it (add `tagOwners` first if the tag is new; [Tailscale](../network/tailscale.md)).
   Add grants and tests to `policies/tailscale/policy.hujson`.
4. `hosts/inventory.yml`: add it to the right groups; `hosts/host_vars/<name>.yml` for its settings.
5. From dgx-1: `site.yml`, `pki.yml`, `fleet-metrics.yml`, `collectors.yml`, `lynis.yml` with `--limit <name>`
   (check, real, second run). Optionally `aibom.yml` (`cisco_aibom_enabled: true`), `k3s.yml` ([k3s](../platform/k3s.md)).
6. Gatus: an `ssh` check in `hosts/stacks/alerting/gatus/config.yaml.j2`; `playbooks/alerting.yml`.
7. Optional: a DNS name (below), restic paths in `host_vars` (`restic_backup_paths`).
8. Update [Hosts](../hosts/index.md) in these docs.

## A service (Docker stack)

1. `hosts/stacks/<name>/compose.yaml` with images pinned by digest, a `restart` policy, memory limits; one sub-folder
   per service for its config; secrets as `*.j2` templates.
2. Publish on `127.0.0.1` or the host's LAN IP, never `0.0.0.0` unless it must be reached on every interface.
3. Secrets: a new key in an existing SOPS file, or a new `secrets/<name>.enc.yaml` (`sops secrets/<name>.enc.yaml`).
4. `hosts/playbooks/<name>.yml`: load the SOPS file with `community.sops.load_vars` (`no_log: true`), then role
   `compose_stack` with `compose_stack_name`, `compose_stack_src`, `compose_stack_env` and
   `compose_stack_private_templates` (`{service: uid}` for files that hold secrets). Copy `jobs.yml` or `ml.yml`.
5. Inventory group if it's a new kind of host.
6. Health: a Gatus check, an `ObservabilityComponentDown`-style scrape if it has metrics (add to
   `victoriametrics/scrape.yml` or the host collector's `otel_host_collector_extra_scrapes`).
7. Web: DNS name + Caddy route + Pocket ID (below), a Homepage tile.
8. A runbook in `runbooks/` if it has operating steps; a page in `docs-site/content/docs/services/`.
9. Deploy (check, real, second run).

## A k3s app

`cluster/apps/<name>/` + `cluster/bootstrap/apps/<name>.yaml` ([Argo CD](../platform/argocd.md)). Requests, limits,
`nodeSelector`, images by digest, Secrets as `*.enc.yaml` + KSOPS generator. Kyverno **enforces** (check with `kyverno apply policies/kyverno --resource <dir>`).

## A Pocket ID client

1. `identity/pocket-id.yaml`: `id`, `name`, `callbackURLs`, `launchURL`, `groups: [admins]`; `pkce: false` only if the app
   can't send PKCE.
2. On dgx-1: `python hosts/files/pocket-id/pocketid_sync.py --dry-run`, then without. The secret goes into SOPS as
   `oidc_<id>_secret`.
3. Commit the YAML and `secrets/console.enc.yaml` together. Wire the app; redeploy ([Pocket ID](../security/identity.md)).

## A DNS name

On dgx-1 in `~/edge-gateway/dnsmasq/dnsmasq.conf` (back up first):

```
address=/myapp.nghodki.ai/192.168.86.44
address=/myapp.nghodki.ai/100.65.137.82
```

`docker restart edge-dnsmasq`; `dig +short @192.168.86.44 myapp.nghodki.ai` and `@100.65.137.82`. Only A records: AAAA
answers NXDOMAIN ([DNS](../network/dns.md)).

## A Caddy route

In `(nghodki_routes)` of `~/edge-gateway/conf/Caddyfile` (back up first), `caddy validate`, `docker restart edge-caddy`
([Front door](../network/front-door.md)). Add the http → https redirect if the app uses Secure cookies or passkeys.

## A Gatus check

An entry under `endpoints:` in `hosts/stacks/alerting/gatus/config.yaml.j2`, LAN IP or front door with a Host header,
`alerts: [{type: ntfy}]`; `playbooks/alerting.yml` ([Gatus](../observability/gatus.md)).

## An alert rule

A rule in `hosts/stacks/observe/vmalert/rules/<file>.yml` with `severity`; `playbooks/observe.yml`; test the route with
`amtool config routes test` ([Alert rules](../observability/alert-rules.md)).

## A NATS user

Password + bcrypt hash in `secrets/bus.enc.yaml`, user and permissions in `hosts/stacks/bus/nats/nats.conf.j2`, the hash
variable in `playbooks/bus.yml`; deploy. Deny the safety reset subjects for anything that isn't a human
([NATS](../services/nats.md)).

## An MCP server for an agent

Export its `tools/list` on the host with `export-mcp-tools.py`, add `tools/<server>/{server.yaml,tools.json}`, add the
server with the same launch to `policies/defenseclaw/mcp-servers.yaml` (and its credential-free env under
`drift_check` if stdio), run `mcp-tool-hashes.py update`, PR. CI scans it; accept reviewed false positives in
`server.yaml`. After the merge: `playbooks/defenseclaw.yml --limit jetson`, then `defenseclaw mcp set <name> ...` as the
account, restart its `hermes-gateway`, run the drift check once ([Agent cards and MCP tools](../agents/cards-and-tools.md)).

## An Edge Connector device

[Edge Connector: add a device](../security/edge-connector.md).

## A grafana dashboard

[Dashboards: add or change](../observability/dashboards.md).
