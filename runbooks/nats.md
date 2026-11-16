# NATS in k3s: the prepared 3-server bus and its cutover

Design: [decision 0014](../decisions/0014-nats-in-k3s.md). Manifests: `cluster/apps/nats/`. Today's server: Docker on
dgx-1 (`bus-nats-1`, `hosts/stacks/bus`, `playbooks/bus.yml`; docs-site page "NATS").

**Status: prepared, not deployed.** Merging the manifests started nothing: no Argo CD Application points at
`cluster/apps/nats` (`argocd-application.yaml` sits there, not in `cluster/bootstrap/apps`), nothing listens on the
NATS VIP, `names.txt` still sends `nats.nghodki.ai` to dgx-1, and every client is on the Docker server. Only two
things took effect at the merge, both inert: Kyverno allows `docker.io/library/nats:` images, and
`tailscale_vip_guard`'s list has `192.168.86.12` (applied when its playbook next runs).

**NATS carries the robot's e-stop** (`robot.pi.safety.estop` / `.reset`, runbooks/robot-safety.md). The cutover is
done **with the user present, the robot docked and the e-stop latched**, never by an agent alone.

## What it is

| | |
|---|---|
| Servers | StatefulSet `nats/nats`, 3 pods, one per node on dgx-1, dgx-2 and the Jetson (required node affinity + anti-affinity; the Jetson's taint tolerated), `podManagementPolicy: Parallel`, PDB `maxUnavailable: 1` |
| Image | `docker.io/library/nats:2.15.3-alpine` by digest (the same as the Docker server) |
| Resources | each: requests 25m / 64 Mi, limits 500m / 256 Mi, `GOMEMLIMIT=200MiB` (measured ~13 MiB per server with MQTT on). The Jetson has ~2.3 GiB for pods |
| Storage | `local-path` PVC `data-nats-N` (4 Gi), JetStream `max_file_store` 2 GB, `max_memory_store` 64 MB |
| JetStream | clustered (`homelab-bus`), every MQTT stream R3 (`mqtt.stream_replicas: 3`); quorum survives one server down |
| Config | `nats.conf` (ConfigMap, hashed): accounts, users and permissions **identical** to `hosts/stacks/bus/nats/nats.conf.j2` (only the password references differ; checked when this was written); `no_advertise` so clients never learn pod IPs |
| Client TLS | Secret `nats-tls` (KSOPS): `hosts/files/pki/nats.crt` (SAN `nats.nghodki.ai`, `spark-83dc`, `192.168.86.44`, `100.65.137.82`, until 2028-11-14) and `pki_nats_key`. Clients connect by name, so the new addresses need no new certificate |
| Passwords | Secret `nats-auth` (KSOPS): `passwords.conf`, the five bcrypt hashes from `secrets/bus.enc.yaml` as NATS variables |
| Routes | port 6222, mutual TLS with their own CA (`certs/route-ca.crt`, CA key discarded; `certs/route.crt` SAN `*.nats-headless.nats.svc.cluster.local`, until 2036; key in Secret `nats-route`). No other homelab certificate can join as a route |
| LAN | Service `nats-lan`: LoadBalancer, **VIP `192.168.86.12`** (kube-vip ARP, lease `plndr-svcs-lock`, the Spark holding `.11`), `:4222` and `:8883`, no NodePorts. Nothing answered `.12` on 2026-11-16 (ping and arping from dgx-1 and the Pi) |
| Tailnet | Service `nats-tailnet` (`tailnet-service.yaml`, **added only at the cutover**): `externalIPs` = both Sparks' Tailscale IPs, `:4222` and `:8883` |
| Monitoring | `:8222` inside the pods only (no Service port on the VIP; NetworkPolicy admits nothing): `kubectl -n nats port-forward pod/nats-N 18222:8222` |
| NetworkPolicy | default deny in and out; 4222/8883 from anywhere (clients arrive masqueraded); 6222 only between the NATS pods; egress only to the other pods' 6222 and kube-dns |
| DNS | `names.txt` target `bus` (in `edge-zone.py`): LAN view → `192.168.86.12`; tailnet view → the answering Spark's Tailscale IP + `192.168.86.12`. Used by `nats` from the cutover on |

Not moving: **fleet-mosquitto** (`:8884`, MQTT 5 for the DefenseClaw Edge Connector, runbooks/edge-connector.md) stays in
Docker on dgx-1; NATS's MQTT is 3.1.1 only.

## The clients (2026-11-16)

Found in the repo and on every host (Pi, Jetson, dgx-1, dgx-2, Dell) by file name and URL, and in `connz` on the
Docker server. All of them use the name `nats.nghodki.ai`, except Gatus:

| Client | Host | URL | Path today | Moves by |
|---|---|---|---|---|
| safety governor (user `picoclaw`) | Pi | `tls://nats.nghodki.ai:4222` (role `safety_governor`) | LAN `192.168.86.44` | DNS |
| `safety-estop` / `safety-reset` | Pi | the same | LAN or tailnet | DNS |
| picoclaw (MQTT client `picoclaw-pi`, user `picoclaw`) | Pi | `ssl://nats.nghodki.ai:8883` (`/var/lib/picoclaw/.picoclaw/config.json`) | **tailnet** `100.65.137.82` | DNS (tailnet view) |
| Hermes' `picoclaw_only` MCP (MQTT `mqttjs_…`, user `hermes`) | Jetson | `MQTT_BROKER=ssl://nats.nghodki.ai:8883` (`~hermes-nikhil/.hermes/config.yaml`) | LAN `192.168.86.44` | DNS |
| `safety-estop` / `safety-reset` (operator) | dgx-1 | `tls://nats.nghodki.ai:4222` (`~/.local/share/safety-cli/cli.json`) | tailnet | DNS |
| Gatus `NATS (TLS)`, `NATS MQTT (picoclaw)` | Dell | `tcp://192.168.86.44:4222`, `:8883` (`hosts/stacks/alerting/gatus/config.yaml.j2`) | LAN | edit + `playbooks/alerting.yml` |

Stale copies (no process uses them): `ssl://192.168.86.34:8883` as the default in the roboclaw MCP servers and old
`config.json` backups on the Pi and the Jetson. dgx-2 and the Dell have no NATS client besides Gatus.

**JetStream state on the Docker server** (`curl -s 127.0.0.1:8222/jsz?accounts=true&streams=true` on dgx-1): five
streams, all the MQTT gateway's own (`$MQTT_sess` 2 messages = the two MQTT sessions, `$MQTT_msgs`, `$MQTT_rmsgs`
(retained) 0, `$MQTT_qos2in`, `$MQTT_out` 0); no stream or KV bucket of our own. **Nothing to migrate**: both MQTT
clients connect with their own client id and re-create their session on the new servers; there are no retained
messages and no QoS 1/2 messages in flight. Check again in step 0 of the cutover; if `$MQTT_rmsgs` has messages then,
stop and decide (retained messages would be lost).

## Cutover

About 45 minutes, most of it waiting for CI. Two PRs: "enable" (phase A, servers start beside Docker, no client moves)
and "move the clients" (phase B). Run everything from dgx-1 in a worktree of the repo with
`export KUBECONFIG=~/.kube/config PATH=$HOME/.local/bin:$PATH` and
`alias nats-verify='~/.local/share/safety-cli/venv/bin/python .github/scripts/nats-verify.py'` (the operator CLI's
Python, which has nats-py). `--fleet-creds` reads the operator's credentials with `sudo -n` and the agent's password
with `sops`; nothing is printed. It publishes only the test subjects `robot.pi.safety.test.estop` / `.test.reset`,
which the deployed governor doesn't listen to.

### 0. Preconditions (user and agent together)

1. **User present** next to the robot for the whole cutover.
2. **Robot docked**, nothing commanding it: on the Pi `sudo systemctl stop picoclaw` (the user; it is restarted in
   B7), `pgrep -fa cmd_vel_bridge` → nothing. If the car has a power switch, switch the motors off.
3. **E-stop latched** and checked, on dgx-1: `safety-estop` → `"state": "estop"`, `"latched": true`; then
   `safety-estop status` → the same, `"sink": {"kind": "mock", "real": false}`. On the Pi:
   `curl -s 127.0.0.1:9113/metrics | grep -E 'estop_latched|nats_connected|real_sink'` → `1`, `1`, `0`.
   The latch lives in the governor's memory: losing NATS during the cutover doesn't clear it, and only
   `safety-reset` (operator) does. The ROS e-stop works without NATS throughout:
   `ros2-kilted topic pub --once /safety/estop std_msgs/msg/Bool "{data: true}"` (Pi or Jetson).
4. Cluster: `kubectl get nodes` all `Ready`; the etcd leader is a Spark (runbooks/k3s.md); Argo CD apps
   Synced/Healthy; on the Jetson `free -m` ≥ 500 MB available.
5. This PR merged: `kubectl get validatingpolicy restrict-registries -o yaml | grep -c library/nats` → not `0`.
6. `.12` still free: from the Pi `sudo arping -c3 -w4 -I wlan0 192.168.86.12` → `Received 0 response(s)`.
7. The VIP guard knows `.12`: in `hosts/`, `ansible-playbook playbooks/tailscale-vip-guard.yml --check --diff`, then
   without `--check` (both Sparks; `nft list table inet tailscale_vip_guard` shows `192.168.86.12`).
8. Baseline: `curl -s '127.0.0.1:8222/connz?auth=1' | python3 -c 'import json,sys; [print(c["ip"], c.get("authorized_user"), c.get("name"), c.get("mqtt_client")) for c in json.load(sys.stdin)["connections"]]'`
   → the governor (`picoclaw`, `safety-governor`) and `hermes` (MQTT), plus `picoclaw-pi` if picoclaw wasn't stopped;
   `curl -s '127.0.0.1:8222/jsz?accounts=true&streams=true'`: no stream outside `$MQTT_*`, `$MQTT_rmsgs` 0 messages.
   `nats-verify --fleet-creds --server tls://nats.nghodki.ai:4222 --checks deny,status --expect-status` →
   `PASS status: state=estop ... estop_latched=True`.

### A. Enable the app (servers start; no client moves)

1. **PR "NATS cutover 1/2: enable"**: `git mv cluster/apps/nats/argocd-application.yaml cluster/bootstrap/apps/nats.yaml`
   (and this runbook's status line). Gated merge. `root` creates the Application within ~3 minutes; Argo CD applies the
   namespace, Secrets, StatefulSet, `nats-headless`, `nats-lan`, PDB and NetworkPolicies. `nats.nghodki.ai` still
   points at dgx-1, so the clients stay on Docker; kube-proxy's DNAT for `192.168.86.12` comes before Docker's rules, so
   the VIP never reaches the Docker server even on dgx-1.
2. Watch: `kubectl -n nats get pods,pvc -o wide` → `nats-0..2` `Running`, `1/1`, one on each of dgx-1, dgx-2, jetson;
   PVCs `Bound`. `kubectl -n nats get svc nats-lan` → `EXTERNAL-IP 192.168.86.12`. `ip -br addr show wlP9s9` on the Sparks:
   `.12` on the one that holds `.11`. `kubectl -n nats logs nats-0 | grep -E 'ERR|WRN'`: route lookup errors in the first
   seconds are normal (the peers' names appear as they start); nothing after.
3. Cluster health (one terminal per pod, or in turn):
   ```bash
   kubectl -n nats port-forward pod/nats-0 18222:8222 >/dev/null & sleep 2
   curl -s 'localhost:18222/healthz?js-enabled-only=true'          # {"status":"ok"}
   curl -s localhost:18222/routez | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sorted({r["remote_name"] for r in d["routes"]}))'   # the other two
   curl -s localhost:18222/jsz | python3 -c 'import json,sys; m=json.load(sys.stdin)["meta_cluster"]; print(m["leader"], m["cluster_size"], [(r["name"], r["current"]) for r in m.get("replicas", [])])'   # size 3, both current
   kill %1
   ```
4. Every path, without the robot:
   ```bash
   for i in 0 1 2; do kubectl -n nats port-forward pod/nats-$i $((14220+i)):4222 >/dev/null & done; sleep 3
   nats-verify --fleet-creds --server tls://192.168.86.12:4222 \
     --server tls://127.0.0.1:14220 --server tls://127.0.0.1:14221 --server tls://127.0.0.1:14222
   nats-verify --fleet-creds --agent-user hermes --server tls://192.168.86.12:4222 --checks deny,mqtt
   kill %1 %2 %3
   ```
   Expect `PASS routes` for all 12 pairs (each server reaches each other), `PASS deny` (picoclaw and hermes may not
   publish the reset subject), `PASS mqtt` both ways over the VIP's `:8883`, `INFO status` (the governor is still on
   Docker), `RESULT: OK`. The first MQTT connection creates the `$MQTT_*` streams; `jsz?streams=true` on a pod shows
   each with `num_replicas` 3.
5. One server down: `kubectl -n nats delete pod <the pod on the jetson>`, and while it restarts
   `nats-verify --fleet-creds --server tls://192.168.86.12:4222 --checks mqtt` → `PASS` (R3 keeps quorum with two).
   Wait for the pod to be `1/1` again.

Stop here if anything failed: roll back with "Rollback, phase A". Nothing has moved yet.

### B. Move the clients

1. **User, Tailscale admin console → Access controls**: apply `policies/tailscale/policy.hujson` from the PR in B2
   (the agent prepares it). The change: one grant
   `{"src": ["tag:agent", "tag:home", "tag:robot"], "dst": ["dgx-2"], "ip": ["tcp:4222", "tcp:8883"]}` next to the
   existing dgx-1 grants (kept), and tests `tag:robot` accept `dgx-2:8883`, `dgx-2:4222`; `tag:agent` accept
   `dgx-2:8883`. Harmless on its own (nothing listens on dgx-2's Tailscale IP :4222/:8883 yet). The Jetson is
   `tag:control` and reaches dgx-2 already.
2. **PR "NATS cutover 2/2: move the clients"** (agent), gated merge:
   - `cluster/platform/edge/names.txt`: `nats  dgx-1` → `nats  bus`; `.github/scripts/edge-zone.py generate`.
   - `cluster/apps/nats/kustomization.yaml`: add `tailnet-service.yaml` to `resources`.
   - `hosts/stacks/alerting/gatus/config.yaml.j2`: the two `bus` checks to `tcp://192.168.86.12:4222` and `:8883`.
   - the policy file from B1; docs: this status, the docs-site "NATS" page, robot-safety.md's troubleshooting line.
   Within ~3 minutes Argo CD rolls the edge CoreDNS pods (new zones) and adds `nats-tailnet`. From then on **new**
   connections go to the cluster (kube-proxy takes dgx-1's Tailscale IP :4222/:8883 from Docker; DNS answers the VIP);
   **established** connections stay on Docker until B4. That is a split bus (an e-stop published on one server doesn't
   reach a subscriber on the other), which is why the e-stop is latched: do B3 and B4 within a few minutes.
3. Check DNS and the new paths:
   ```bash
   dig +short nats.nghodki.ai @192.168.86.11        # 192.168.86.12
   dig +short nats.nghodki.ai @100.65.137.82        # 100.65.137.82 and 192.168.86.12
   dig +short nats.nghodki.ai @100.124.175.23       # 100.124.175.23 and 192.168.86.12
   kubectl -n nats get svc nats-tailnet             # EXTERNAL-IP 100.65.137.82,100.124.175.23
   nats-verify --fleet-creds --server tls://100.65.137.82:4222 --server tls://100.124.175.23:4222 --checks routes,deny,mqtt
   ```
   (`--server` sets the address; the certificate is checked against `nats.nghodki.ai`.) On the Pi:
   `getent ahosts nats.nghodki.ai` → `100.65.137.82` or `100.124.175.23`, and `192.168.86.12`.
4. **Stop the Docker server** (dgx-1): `docker stop bus-nats-1`. Its container and volume `bus_nats-data` stay for the
   rollback (`unless-stopped`: it stays stopped across reboots). The governor, Hermes and the CLIs reconnect within
   seconds; they resolve `nats.nghodki.ai` again and land on the cluster.
5. **E-stop path, end to end, no motion** (the sink is the mock; picoclaw is stopped):
   - dgx-1: `nats-verify --fleet-creds --server tls://nats.nghodki.ai:4222 --expect-status` → `PASS status:
     state=estop ... estop_latched=True`: the governor publishes through the cluster.
   - Pi: `curl -s 127.0.0.1:9113/metrics | grep nats_connected` → `1`; `journalctl -t safety-governor --since -10min | grep -i nats`
     shows the reconnect. Pi: `safety-estop status` (as picoclaw, through the cluster) → `estop`.
   - The reset path and the Pi's e-stop path, through the cluster: dgx-1 `safety-reset` → exits 0, the governor reports
     clear; **at once** Pi `safety-estop` → `"latched": true`, `latched by nats`. Seconds apart, nothing commanding,
     sink mock: no motion is possible. Pi `journalctl -t safety-governor -n 20 | grep INTERVENTION` → `kind=reset`,
     then `kind=estop`.
   - Hermes' path (MQTT): `nats-verify --fleet-creds --agent-user hermes --server tls://nats.nghodki.ai:4222 --checks mqtt`
     → both directions `PASS`. Optional: ask Hermes to stop the robot (its `stop` tool, `robot/pi/safety/estop`): the
     journal shows a second `kind=estop` (it is latched already).
   - Who is connected (any pod, `port-forward ... 18222:8222`):
     `curl -s 'localhost:18222/connz?auth=1&subs=1'` per pod: the governor (`picoclaw`, `safety-governor`, subscribed to
     `robot.pi.safety.estop` and `.reset`), `hermes` (MQTT, subscribed under `/.picoclaw.`). Only one server holds a
     given client; check all three.
6. **Gatus**: in `hosts/`, `ansible-playbook playbooks/alerting.yml --check --diff`, then for real. Group `bus` green
   on `192.168.86.12`.
7. **User**: on the Pi `sudo systemctl start picoclaw`; within a minute `connz?auth=1` shows MQTT client `picoclaw-pi`
   on one of the servers. Hermes' MCP reconnects by itself (mqtt.js resubscribes); if `hermes` has no
   `/.picoclaw.` subscription, restart its gateway: `sudo -u hermes-nikhil XDG_RUNTIME_DIR=/run/user/$(id -u hermes-nikhil)
   systemctl --user restart hermes-gateway` (Jetson). Then the user clears the e-stop with `safety-reset` when ready.
8. A day later: the failover drill's NATS part (delete one NATS pod while a client publishes test e-stops; the client
   reconnects through the VIP), recorded in decision 0014. Then a follow-up PR: retire the Docker server
   (`playbooks/bus.yml` keeps the "Operator safety CLI" play only; `docker rm bus-nats-1` and its volume after 7 days),
   drop the dgx-1 grants for 4222/8883 if nothing uses them.

**Don't run `playbooks/bus.yml`** after B4 until that follow-up: it would start `bus-nats-1` again (`compose up`), a
second, separate bus on dgx-1's LAN IP.

## Rollback

The robot stays docked and latched until a rollback is finished; the ROS e-stop works throughout.

**Phase A** (clients never moved): revert the enable PR (or `git mv` the Application back). Argo CD deletes the app's
resources (finalizer), the namespace with them; the local-path volumes are deleted with their PVCs.

**Phase B** (after B2/B4): one bus at a time, never both serving clients.

1. Stop the cluster serving clients, then bring Docker back:
   ```bash
   kubectl -n argocd patch application nats --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
   kubectl -n nats delete svc nats-lan nats-tailnet      # VIP gone; dgx-1's Tailscale IP back to Docker
   docker start bus-nats-1                               # dgx-1: 0.0.0.0:4222/8883 again
   ```
2. Revert PR 2/2 (gated merge): `nats` back to `dgx-1`, `tailnet-service.yaml` out, Gatus back on `.44`. Until it is
   in, the LAN view still answers `.12` (now silent): clients on the tailnet view fall back to the Tailscale IP, which
   is Docker again.
3. Check as in step 0.8 on the Docker server (`connz`: the governor and hermes back), `safety-estop status`.
4. Revert PR 1/2 too (phase A rollback) or re-enable auto-sync for another attempt.

## Operations (after the cutover)

- **Rolling restart / config change**: a change to `nats.conf` rolls the pods one at a time (hashed ConfigMap). Each
  pod enters lame duck (30 s) in `preStop`, so its clients move to the other two through the VIP. A Secret change
  (`nats-auth`, `nats-tls`) needs `kubectl -n nats rollout restart statefulset nats` after Argo CD has synced.
- **Add a user / change a permission**: as on the docs-site "NATS" page (`secrets/bus.enc.yaml`, bcrypt), then
  regenerate `nats-auth.enc.yaml` (below) and edit `nats.conf`; keep `nats.conf.j2` the same until the Docker server is
  retired.
- **A node down**: two servers keep JetStream quorum; the pod on the dead node isn't rescheduled (local volume,
  anti-affinity). Clients reconnect through the VIP within seconds (kube-proxy drops the dead endpoints after the
  node grace period, ~20 s, runbooks/edge.md "Failover"). Both Sparks down: no quorum, no bus (the Jetson alone).
- **The Jetson's memory**: `kubectl top pod -n nats`; limit 256 Mi.

### Certificates and secrets

Regenerate a Secret from SOPS without printing it (from a worktree; `sops` uses the age key on dgx-1):

```bash
python3 - <<'PY' | sops --encrypt --input-type yaml --output-type yaml \
    --filename-override cluster/apps/nats/nats-auth.enc.yaml /dev/stdin > cluster/apps/nats/nats-auth.enc.yaml
import json, subprocess
d = json.loads(subprocess.run(["sops", "-d", "--output-type", "json", "secrets/bus.enc.yaml"],
                              capture_output=True, text=True, check=True).stdout)
lines = ["# NATS variables for nats.conf (users' bcrypt hashes; from secrets/bus.enc.yaml)"]
lines += [f'NATS_{u.upper()}_PASSWORD_HASH: "{d[f"nats_{u}_password_hash"]}"' for u in ["admin", "picoclaw", "hermes", "operator", "sys"]]
print("apiVersion: v1\nkind: Secret\nmetadata:\n  name: nats-auth\n  namespace: nats\ntype: Opaque\nstringData:")
print("  passwords.conf: |\n" + "\n".join("    " + l for l in lines))
PY
```

`nats-tls.enc.yaml` the same way from `hosts/files/pki/nats.crt` and `pki_nats_key` in `secrets/pki.enc.yaml` (as
`web-tls` in runbooks/edge.md). Renew `nats.crt` before 2028-11-14 (docs-site "PKI"): commit the new certificate and
key, regenerate `nats-tls.enc.yaml`, merge, `kubectl -n nats rollout restart statefulset nats`.

The route certificate (`certs/route.crt`, until 2036) has its own CA, whose key was deleted after signing: to renew,
make a new CA and certificate together (`openssl`, ECDSA P-256, `pathlen:0`; leaf EKU serverAuth + clientAuth, SAN
`*.nats-headless.nats.svc.cluster.local`), commit `certs/route-ca.crt` and `certs/route.crt`, put the new key in
`nats-route.enc.yaml`, and restart all three pods at once (old and new routes don't trust each other).
