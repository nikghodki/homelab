---
title: Gatus checks
description: Every uptime check Gatus runs from the Dell, what passes, and how to add one.
---

Gatus 5.38.0 runs on the Dell (`hosts/stacks/alerting`, `playbooks/alerting.yml`). It checks the fleet **from
outside the Sparks**, using LAN addresses or the front door, never container names. Config:
`hosts/stacks/alerting/gatus/config.yaml.j2` (authoritative). Storage: SQLite in the `alerting_gatus-data` volume.

Every check alerts to ntfy (topic `fleet-alerts`, priority 4, token auth) after **3** failures and resolves after
**2** successes. Status page: `https://status.nghodki.ai` (Pocket ID). Metrics: `/metrics` (scraped by dgx-2, used by
the k3s alerts and the dead man).

## Checks

| Group | Name | Target | Passes when |
|---|---|---|---|
| web | model.nghodki.ai (LiteLLM) | `http://192.168.86.44/health/liveliness`, Host `model.nghodki.ai` | 200 |
| web | webui.nghodki.ai | `http://192.168.86.44/`, Host `webui...` | below 400 |
| web | dgxmanager.nghodki.ai | `http://192.168.86.44/`, Host `dgxmanager...` | below 400 |
| web | ha.nghodki.ai | `http://192.168.86.44/`, Host `ha...` | below 400 |
| web | ops.nghodki.ai (Homepage) | `https://192.168.86.44/`, Host `ops...`, no redirect follow | 302 (to Pocket ID) |
| web | ntfy.nghodki.ai | `https://192.168.86.44/v1/health` | 200 and `healthy == true` |
| web | status.nghodki.ai | `https://192.168.86.44/health` | below 400 |
| web | `*.nghodki.ai certificate` | `https://192.168.86.44/`, Host `webui...`, hourly | below 400 and cert valid > 720 h (30 days) |
| home | Home Assistant (direct) | `http://192.168.86.211:8123/` | below 400 |
| observe | Phoenix | `http://192.168.86.36:6006/healthz` | below 400 |
| observe | Grafana | `http://192.168.86.36:3000/api/health` | 200 and `database == ok` |
| observe | grafana.nghodki.ai | `https://192.168.86.44/api/health` | below 400 |
| observe | alert pipeline heartbeat (external endpoint) | Alertmanager posts every 5 min | a post within 15 min |
| jobs | Temporal frontend (gRPC) | `tcp://192.168.86.36:7233` | connected |
| jobs | temporal.nghodki.ai | `https://192.168.86.44/healthz` | below 400 |
| ml | mlflow.nghodki.ai | `https://192.168.86.44/`, no redirect follow | 302 |
| ml | MLflow job API | `http://192.168.86.36:5000/health` | 200 and body `OK` |
| bus | NATS (TLS) | `tcp://192.168.86.44:4222` | connected |
| bus | NATS MQTT (picoclaw) | `tcp://192.168.86.44:8883` | connected |
| defenseclaw | Fleet MQTT (Edge Connector) | `tcp://192.168.86.44:8884` | connected |
| defenseclaw | Fleet API | `https://192.168.86.44:8971/api/v1/fleet/health`, Host `fleet...` | 401 (proxy, gateway and Fleet up) and cert > 336 h |
| hosts | dgx-1 / dgx-2 / jetson / omarchy / pi ssh | `tcp://<LAN IP>:22` | connected |
| robot | Zenoh router (ROS 2) | `tcp://192.168.86.211:7447` | connected (port only, not that `/scan` flows) |
| k3s | API dgx-1, API dgx-2 | `https://192.168.86.44:6443/readyz`, `.36` | 401 (anonymous off = answering) and cert > 720 h |
| k3s | etcd dgx-1, dgx-2, jetson | `tcp://10.100.136.1:2379`, `10.100.136.2:2379`, `192.168.86.211:2379` | connected |

The Dell has no route to 10.100.136.0/24 except the /32s that k3s added, which is how it reaches the Spark etcd
addresses.

Gatus has neither CA in its image, so HTTPS checks use `insecure: true` and only check status and expiry.

## Sign-in

Gatus itself has **no login** and listens only on the Dell's loopback (127.0.0.1:8082). `status-proxy` (oauth2-proxy
7.15.6, client `gatus`) is published on 192.168.86.49:8081. Without a session it lets through only `GET /health`,
`GET /metrics` and `POST /api/v1/endpoints/<key>/external` (the heartbeat, which Gatus checks with its own token,
`gatus_heartbeat_token`). Gatus' own OIDC isn't used because it panics at start when Pocket ID is unreachable.

## Add a check

1. Add an entry to `endpoints:` in `config.yaml.j2`. Use a LAN IP or `https://192.168.86.44/` with a `Host` header.
   Add `alerts: [{type: ntfy}]`.
2. `ansible-playbook playbooks/alerting.yml --check --diff`, then without `--check`. Gatus re-reads its config by
   itself; the role restarts it anyway.
3. Never add checks that use Spark container names, and never move Gatus back into the observe stack.
