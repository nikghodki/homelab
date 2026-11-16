---
title: Gatus and ntfy (alerting stack)
description: The alerting stack on the Dell as a deployable unit. Checks and delivery are documented in the observability section.
---

| | |
|---|---|
| Host | the Dell, stack `alerting` (`hosts/stacks/alerting`, `playbooks/alerting.yml`, `/opt/homelab/alerting`) |
| Containers | `gatus` (5.38.0, 127.0.0.1:8082), `status-proxy` (oauth2-proxy 7.15.6, 192.168.86.49:8081), `ntfy` (2.38.0, 127.0.0.1:8085 and 192.168.86.49:8085) |
| URLs | `https://status.nghodki.ai` (front door → status-proxy), `https://ntfy.nghodki.ai` (front door → ntfy), `https://nikghodki-omarchy-1.tail1cb707.ts.net` (Tailscale HTTPS → ntfy, what the phone uses) |
| Secrets | `observe` → `ntfy_alerts_password_hash`, `ntfy_alerts_token`, `ntfy_phone_password_hash`, `gatus_heartbeat_token`; `console` → `oidc_gatus_secret`, `oauth2_proxy_status_cookie_secret` |
| Private templates | status-proxy renders 0600 for uid 65532 |
| Also does | enables `docker.service` at boot (Arch), and `tailscale serve --bg --https=443 http://127.0.0.1:8085` (role `tailscale_serve`) |
| Data | volumes `alerting_gatus-data` (SQLite), `alerting_ntfy-data` (cache and `user.db`, rebuilt from config) |
| Health | from dgx-2: `AlertingHostDown` (scrape of `/metrics`), `AlertDeliveryFailing`; from Gatus itself: `status.nghodki.ai`, `ntfy.nghodki.ai` |
| k3s target | none: stays on the Dell, outside the cluster, so alerting never depends on it |

Deploy: `ansible-playbook playbooks/alerting.yml --check --diff`, then without `--check`.

Details: [Gatus checks](../observability/gatus.md), [Alert delivery](../observability/alert-delivery.md).
