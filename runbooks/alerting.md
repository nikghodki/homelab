# Alerting: how alerts reach the phone

The alert path runs on the Dell (Omarchy, `192.168.86.49`), not on a Spark. Both Sparks can crash together (GPU memory
exhaustion, 2026-11-15), and when Gatus and ntfy lived on dgx-2 nobody was told. The Dell is always on and never sleeps
(role `always_on`).

```
 vmalert ──▶ Alertmanager (dgx-2 observe stack) ──LAN http──▶ ntfy (Dell :8085) ──Tailscale HTTPS──▶ phone (ntfy app)
                    │                                             ▲
                    └─ Watchdog heartbeat every 5 min ──▶ Gatus (Dell :8081) ──┘  (Gatus alerts on its own checks too,
                                                          alerts if the heartbeat stops for 15 min)
```

| Piece | Where |
|---|---|
| Gatus 5.38.0, ntfy 2.38.0 | Dell, `hosts/stacks/alerting` (`playbooks/alerting.yml`), `/opt/homelab/alerting` |
| Status-page sign-in | `status-proxy` (oauth2-proxy 7.15.6, Pocket ID client `gatus`) on `192.168.86.49:8081`; without a session only `/health`, `/metrics` and the heartbeat POST pass. Gatus itself listens on the Dell's loopback (`127.0.0.1:8082`) |
| Gatus config (authoritative) | `hosts/stacks/alerting/gatus/config.yaml.j2`; checks use LAN addresses or the front door, never container names |
| ntfy config | `hosts/stacks/alerting/ntfy/server.yml.j2`; users, access and tokens are declared there from `secrets/observe.enc.yaml` |
| Tailscale HTTPS | `tailscale serve` on the Dell (role `tailscale_serve`): `https://nikghodki-omarchy-1.tail1cb707.ts.net` → `127.0.0.1:8085` |
| Alertmanager | dgx-2, `hosts/stacks/observe/alertmanager/alertmanager.yml.j2`; posts to `http://192.168.86.49:8085/fleet-alerts` |
| Heartbeat | `hosts/stacks/observe/vmalert/rules/watchdog.yml` → Alertmanager route `gatus-heartbeat` → Gatus external endpoint `observe_alert-pipeline-heartbeat` |
| Never sleep | `hosts/roles/always_on` (`playbooks/always-on.yml`, also in `site.yml`) |
| Web routes | dgx-1 Caddy: `status.nghodki.ai` → `192.168.86.49:8081`, `ntfy.nghodki.ai` → `192.168.86.49:8085` ([web-https.md](web-https.md)) |

## The phone

In the ntfy app (iPhone, on the tailnet as nikghodki):

- Server: `https://nikghodki-omarchy-1.tail1cb707.ts.net` (no port, no path). It must be exactly this: it's ntfy's
  `base-url`, and the iOS app's instant notifications (relayed by `upstream-base-url: https://ntfy.sh`, which only sees a
  hash of the URL and topic, never the text) only work when the two match.
- Topic: `fleet-alerts`. User: `nikhil` (password `ntfy_phone_password` in `secrets/observe.enc.yaml`; read-only).
- Tailscale must be connected on the phone. It works on mobile data too, and doesn't need dgx-1 (front door, DNS) or dgx-2.

`https://ntfy.nghodki.ai` still works (same server, through dgx-1), but only while dgx-1 is up, and the iOS app gets no
instant push for it. Don't subscribe twice.

## What still depends on what

| If this is down | Alerts |
|---|---|
| dgx-2 (VictoriaMetrics, vmalert, Alertmanager, Grafana) | Metric alerts stop. Gatus on the Dell alerts on dgx-2's checks (ssh, Grafana, Phoenix, Temporal, MLflow, k3s API) and, after 15 min, on the missing heartbeat |
| dgx-1 (front door, DNS, NATS, LiteLLM) | Phone still gets alerts over Tailscale. `status.nghodki.ai`, `ntfy.nghodki.ai` and `ops.nghodki.ai` don't open (and Pocket ID, behind the front door, can't sign anyone in); Gatus keeps checking because it has no OIDC of its own. UI: `ssh -L 8082:127.0.0.1:8082 nikghodki@192.168.86.49` |
| Both Sparks | Gatus on the Dell alerts on every Spark check; ntfy delivers to the phone |
| The Dell | No Gatus, no ntfy: nothing reaches the phone. Alertmanager's notifications fail (visible in its log and `alertmanager_notifications_failed_total`). Nothing outside the house watches the Dell yet |
| Home Wi-Fi / internet | LAN checks still run. The phone gets alerts only if it is on the home Wi-Fi or the Dell can reach Tailscale; iOS instant push needs ntfy.sh |
| Tailscale control plane | Existing connections keep working; new ones may not |

## Checks

```bash
# from dgx-1
curl -s http://192.168.86.49:8085/v1/health                     # ntfy on the LAN
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.86.49:8081/health   # Gatus, through status-proxy
ssh -n nikghodki@192.168.86.49 'sudo tailscale serve status'    # https://nikghodki-omarchy-1... -> 127.0.0.1:8085
ssh -n nikghodki@192.168.86.49 'sudo docker logs --since 10m alerting-gatus-1 | grep -E "success=false|TRIGGERED|RESOLVED|external"'
# read the topic as the phone user without printing the password
PW=$(sops -d --extract '["ntfy_phone_password"]' secrets/observe.enc.yaml)
printf 'user = "nikhil:%s"\n' "$PW" | curl -s -K - 'http://192.168.86.49:8085/fleet-alerts/json?poll=1&since=1h'; unset PW
```

The Tailscale policy lets admins (the phone) reach the Dell on any port; dgx-1 and dgx-2 only reach it on 22 over
Tailscale, so test the HTTPS URL from an admin device (phone, MacBook Air), not from a Spark.

Test an alert end to end: add one in Alertmanager on dgx-2
(`docker exec observe-alertmanager-1 amtool --alertmanager.url=http://127.0.0.1:9093 alert add Test severity=warning`),
wait 30 s, look for it on the phone, then resolve it (POST it to `/api/v2/alerts` with `endsAt` = now).

## Change things

- Checks: edit `hosts/stacks/alerting/gatus/config.yaml.j2`, then from `hosts/`: `ansible-playbook playbooks/alerting.yml --check --diff`,
  then without `--check`. Gatus re-reads its config by itself; the role restarts it anyway.
- Users/tokens: change the hash in SOPS (`ntfy user hash` in the ntfy image prints one), redeploy. ntfy rebuilds `user.db` from the config.
- Never re-add Gatus or ntfy to the observe stack, and keep Gatus checks off Spark container names.

## Moving it (2026-11-15) and rolling back

ntfy was started fresh on the Dell: users, access and tokens are declarative, so the same accounts and token work; only
ntfy's 12 h message cache stayed behind. Gatus also started with empty history. The old volumes `observe_gatus-data` and
`observe_ntfy-data` are still on dgx-2; delete them once the Dell has run a week
(`docker volume rm observe_gatus-data observe_ntfy-data`).

Roll back: restore dgx-1's Caddyfile from `~/edge-gateway/conf/Caddyfile.bak-dell-alerting-*`, `docker restart edge-caddy`,
then revert the PR and redeploy `playbooks/observe.yml` and `playbooks/console.yml` (they bring Gatus, ntfy and Homepage back on dgx-2).
