# Alerting: how alerts reach the phone

The alert path runs on the Dell (Omarchy, `192.168.86.49`), not on a Spark. Both Sparks can crash together (GPU memory
exhaustion, 2026-11-15), and when Gatus and ntfy lived on dgx-2 nobody was told. The Dell is always on and never sleeps
(role `always_on`).

```
 vmalert ──▶ Alertmanager (dgx-2 observe stack) ──LAN http──▶ ntfy (Dell :8085) ──Tailscale HTTPS──▶ phone (ntfy app)
                    │                                             ▲
                    └─ Watchdog heartbeat every 5 min ──▶ Gatus (Dell :8081) ──┘  (Gatus alerts on its own checks too,
                                                          alerts if the heartbeat stops for 15 min)

 The Dell itself (dead man, off the Dell):
 VictoriaMetrics scrapes the Dell's Gatus ──▶ vmalert AlertingHostDown (15 min) ──▶ Alertmanager ──HTTPS──▶ ntfy.sh
 (job "gatus", every 30 s)                                                      (random topic, fixed text) ──▶ phone
```

| Piece | Where |
|---|---|
| Gatus 5.38.0, ntfy 2.38.0 | Dell, `hosts/stacks/alerting` (`playbooks/alerting.yml`), `/opt/homelab/alerting` |
| Status-page sign-in | at the front door (`edge-auth`, [sign-in.md](sign-in.md), decision 0011). On the Dell, `status-gate` (Caddy) on `192.168.86.49:8081` passes the UI only with the front door's `X-Edge-Origin` token; `/health`, `/metrics` and the heartbeat POST pass without it. Gatus itself listens on the Dell's loopback (`127.0.0.1:8082`); none of this is on the checking path |
| Gatus config (authoritative) | `hosts/stacks/alerting/gatus/config.yaml.j2`; checks use LAN addresses or the front door, never container names |
| ntfy config | `hosts/stacks/alerting/ntfy/server.yml.j2`; users, access and tokens are declared there from `secrets/observe.enc.yaml` |
| Tailscale HTTPS | `tailscale serve` on the Dell (role `tailscale_serve`): `https://nikghodki-omarchy-1.tail1cb707.ts.net` → `127.0.0.1:8085` |
| Alertmanager | dgx-2, `hosts/stacks/observe/alertmanager/alertmanager.yml.j2`; posts to `http://192.168.86.49:8085/fleet-alerts` |
| Heartbeat | `hosts/stacks/observe/vmalert/rules/watchdog.yml` → Alertmanager route `gatus-heartbeat` → Gatus external endpoint `observe_alert-pipeline-heartbeat` |
| Never sleep | `hosts/roles/always_on` (`playbooks/always-on.yml`, also in `site.yml`) |
| Dead man for the Dell | `hosts/stacks/observe/vmalert/rules/alerting-host.yml` → Alertmanager receivers `ntfy-sh-backup-host` / `ntfy-sh-backup-delivery` → public `https://ntfy.sh/<topic>`; topic `ntfy_sh_backup_topic_token` in `secrets/observe.enc.yaml` |
| Web routes | the in-cluster Caddy: `status.nghodki.ai` → `192.168.86.49:8081` (signed in, `/health` open), `ntfy.nghodki.ai` → `192.168.86.49:8085` ([edge.md](edge.md)) |

## The phone

In the ntfy app (iPhone, on the tailnet as nikghodki):

- Server: `https://nikghodki-omarchy-1.tail1cb707.ts.net` (no port, no path). It must be exactly this: it's ntfy's
  `base-url`, and the iOS app's instant notifications (relayed by `upstream-base-url: https://ntfy.sh`, which only sees a
  hash of the URL and topic, never the text) only work when the two match.
- Topic: `fleet-alerts`. User: `nikhil` (password `ntfy_phone_password` in `secrets/observe.enc.yaml`; read-only).
- Tailscale must be connected on the phone. It works on mobile data too, and doesn't need dgx-1 (front door, DNS) or dgx-2.

`https://ntfy.nghodki.ai` still works (same server, through dgx-1), but only while dgx-1 is up, and the iOS app gets no
instant push for it. Don't subscribe twice.

Second subscription, once: the backup topic on public ntfy.sh (when the Dell is down, this is the only path).

1. Read the topic on dgx-1, in the repo: `sops -d --extract '["ntfy_sh_backup_topic_token"]' secrets/observe.enc.yaml`
   (don't paste it anywhere public; anyone who knows it can read and post to it).
2. ntfy app → **+** → Topic: the value from step 1 → turn on **Use another server** → `https://ntfy.sh` → **Subscribe**.
   No user or password. Notifications on (it's sent with priority urgent).
3. Messages there are only `homelab: alerting host unreachable` or `homelab: alert delivery failing`, title `homelab`.
   They mean: look at the Dell (and the Dell's ntfy topic won't have anything).

## Dead man for the Dell

Gatus and ntfy can't report their own host being down, so the check runs on dgx-2 and the message goes around the Dell:

- **Check:** vmalert `AlertingHostDown`: `max(up{job="gatus"}) < 1 or absent(up{job="gatus"})` for 15 min. dgx-2's
  VictoriaMetrics scrapes the Dell's Gatus `/metrics` (`192.168.86.49:8081`, through status-gate) every 30 s, so this
  is "the Dell, its Docker, status-gate or Gatus is down, or dgx-2 can't reach it". `AlertDeliveryFailing`
  (Alertmanager's webhook notifications kept failing for 15 min, e.g. the Dell's ntfy broken while Gatus answers) uses
  the same path; it is inhibited while `AlertingHostDown` fires.
- **Delivery:** Alertmanager posts straight to public `https://ntfy.sh/<topic>` (dgx-2 → internet; no Dell, no
  Tailscale, no dgx-1). Why ntfy.sh: it needs no account or extra service, the phone already runs the ntfy app, and
  ntfy.sh is what the Dell's ntfy uses for iOS push anyway. The topic is 128 random bits (only in SOPS and the
  rendered `alertmanager.yml` on dgx-2; Alertmanager shows webhook URLs as `<secret>`).
- **Content-free:** the URL uses ntfy's template mode (`tpl=1`) with a fixed `t=homelab` and `m=...`, so ntfy.sh
  stores and shows only that text, never the alert JSON. The alerts' labels and annotations carry no hostnames or
  addresses (`max()` drops `instance`), because the webhook body still goes to ntfy.sh. `send_resolved: false`;
  repeats every 4 h while it lasts.
- **Not covered:** dgx-2 down at the same time as the Dell (then nothing is left to notice), or the house's internet
  down (dgx-2 can't reach ntfy.sh; the phone couldn't reach the Dell either).

Test (2026-11-15): an `amtool` alert with the dead-man labels went to `ntfy-sh-backup-host` and the fixed message was on
the topic within seconds:

```bash
# on dgx-2
docker exec observe-alertmanager-1 amtool --alertmanager.url=http://127.0.0.1:9093 config routes test alertname=AlertingHostDown
docker exec observe-alertmanager-1 amtool --alertmanager.url=http://127.0.0.1:9093 alert add AlertingHostDown severity=critical \
  --annotation='summary="alerting host unreachable"' --end=$(date -u -d '+3 min' +%Y-%m-%dT%H:%M:%SZ)
# on dgx-1, without printing the topic
T=$(sops -d --extract '["ntfy_sh_backup_topic_token"]' secrets/observe.enc.yaml)
curl -s "https://ntfy.sh/$T/json?poll=1&since=5m" | jq -c '{title, message, priority}'; unset T
```

## What still depends on what

| If this is down | Alerts |
|---|---|
| dgx-2 (VictoriaMetrics, vmalert, Alertmanager, Grafana) | Metric alerts stop. Gatus on the Dell alerts on dgx-2's checks (ssh, Grafana, Phoenix, Temporal, MLflow, k3s API) and, after 15 min, on the missing heartbeat |
| dgx-1 (front door, DNS, NATS, LiteLLM) | Phone still gets alerts over Tailscale. `status.nghodki.ai`, `ntfy.nghodki.ai` and `ops.nghodki.ai` don't open (and Pocket ID, behind the front door, can't sign anyone in); Gatus keeps checking because it has no OIDC of its own. UI: `ssh -L 8082:127.0.0.1:8082 nikghodki@192.168.86.49` |
| Both Sparks | Gatus on the Dell alerts on every Spark check; ntfy delivers to the phone |
| The Dell | No Gatus, no ntfy. After 15 min dgx-2 sends `AlertingHostDown` to the backup topic on ntfy.sh (content-free). Other alerts fail to deliver until it's back (Alertmanager's log, `alertmanager_notifications_failed_total`) |
| The Dell and dgx-2 | Nothing reaches the phone |
| Home Wi-Fi / internet | LAN checks still run. The phone gets alerts only if it is on the home Wi-Fi or the Dell can reach Tailscale; iOS instant push needs ntfy.sh |
| Tailscale control plane | Existing connections keep working; new ones may not |

## Checks

```bash
# from dgx-1
curl -s http://192.168.86.49:8085/v1/health                     # ntfy on the LAN
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.86.49:8081/health   # Gatus, through status-gate
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

The Watchdog is always firing, so it shows in `ALERTS`. Fleet home filters it out; the DefenseClaw overview is vendored
from upstream (CI checks it's unchanged), so its firing-alerts count is one higher than the real alerts.

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
