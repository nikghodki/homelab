---
title: "Observe stack (Grafana, VictoriaMetrics, Loki, Tempo, vmalert, Alertmanager)"
description: "The observability services on dgx-2 as a deployable unit: containers, ports, config files, secrets, deploy and health."
---

| | |
|---|---|
| Host | dgx-2, stack `observe` (`hosts/stacks/observe`, `playbooks/observe.yml`, `/opt/homelab/observe`) |
| URL | `https://grafana.nghodki.ai` (Grafana). The rest have no web route |
| k3s target | `observe` |

| Container | Version | Published | Config in the repo |
|---|---|---|---|
| victoriametrics | v1.156.0 | — (8428 on the stack network) | `victoriametrics/scrape.yml` (stack self-scrapes, Gatus, Temporal, Argo CD, Kyverno, kube-state-metrics); also takes Tempo's remote write |
| vmalert | v1.156.0 | — | `vmalert/rules/*.yml`, 30 s evaluation |
| alertmanager | v0.35.0 | — | `alertmanager/alertmanager.yml.j2` |
| loki | 3.7.10 | — | `loki/loki.yaml` (adapted from DefenseClaw 1.0.9; 30 days) |
| tempo | 2.10.10 | — | `tempo/tempo.yaml` (adapted; 30 days); the metrics generator remote-writes to `victoriametrics:8428` (#74; there is no Prometheus in the stack) |
| otel-defenseclaw | collector-contrib 0.165.0 | 4317, 4318 | `otel-defenseclaw/config.yaml` (adapted) |
| otel-fleet | collector-contrib 0.165.0 | 4319, 4320 | `otel-fleet/config.yaml` |
| grafana | 13.3.1 | 3000 | `grafana/provisioning/`, `grafana/dashboards/`; home dashboard Fleet Home |
| phoenix | 21.1.0 | 6006 | env in `compose.yaml` ([Phoenix](phoenix.md)) |

Which files come from DefenseClaw is declared in `hosts/stacks/observe/defenseclaw-bundle.yaml` (verbatim: dashboards,
`defenseclaw-alerts.yml`, `defenseclaw-recording.yml`; adapted: loki, tempo, otel-defenseclaw, with upstream sha256s).

## Secrets

`.env` from SOPS: `GRAFANA_ADMIN_PASSWORD` (`observe` → `grafana_admin_password`), `PHOENIX_SECRET`,
`PHOENIX_ADMIN_PASSWORD`, `OIDC_GRAFANA_SECRET`, `OIDC_PHOENIX_SECRET` (`console`). The Alertmanager template uses
`ntfy_alerts_password`, `gatus_heartbeat_token`, `ntfy_sh_backup_topic_token`.

## Grafana sign-in

Generic OAuth with Pocket ID (PKCE), scopes `openid email profile groups`, role mapping
`contains(groups[*], 'admins') && 'GrafanaAdmin' || 'Viewer'` (strict), sign-up allowed for OAuth users, anonymous off,
local sign-up off. The local `admin` stays as break-glass. Grafana reaches `id.nghodki.ai` through
`extra_hosts` and trusts the web CA via the host bundle.

## Deploy, health

```bash
ansible-playbook playbooks/observe.yml --check --diff && ansible-playbook playbooks/observe.yml
curl -s http://192.168.86.36:3000/api/health          # {"database":"ok",...}
ssh nikghodki-dgx-2@192.168.86.36 'sudo docker compose --project-directory /opt/homelab/observe ps'
```

Gatus checks Grafana directly and through the front door. VictoriaMetrics, vmalert and Alertmanager aren't on the LAN;
the Watchdog heartbeat to Gatus covers them.

## Depends on

dgx-2 itself; host collectors (data); Pocket ID (sign-in only); the Dell (alert delivery).

## Gotchas

- Never re-add Gatus or ntfy to this stack: deploying a stale branch's `observe` would also remove services added since
  (`remove_orphans`). Rebase first.
- The DefenseClaw files are vendored: CI fails if they're edited by hand.
