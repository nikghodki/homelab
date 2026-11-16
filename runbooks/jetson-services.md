# Jetson home services: Home Assistant and LiveKit

Both were hand-run until 2026-11-15 (tool review 2026-11 §2.17, design F4). Now `playbooks/home.yml` deploys them.

| | Home Assistant | LiveKit server |
|---|---|---|
| What | Home control; Hermes' `homeassistant` MCP server (runbooks/mcp-admission.md) | WebRTC server the RoboClaw control center (`:8200`) uses; the voice route is retired (D26) |
| Runs as | Docker container `homeassistant`, compose project `home-assistant` | systemd **user** unit `livekit-server.service` (nikjetson) |
| In Git | `hosts/stacks/home-assistant/compose.yaml` → `/opt/homelab/home-assistant` | role `livekit`: binary `/opt/livekit/<version>/livekit-server`, `~/.config/livekit/livekit.yaml` (0600), the unit |
| Version | `2026.11.1`, pinned by digest (Renovate PRs) | `1.13.5`, release tarball checked by SHA-256 (`roles/livekit/defaults`) |
| Listens | host network, `:8123` (`https://ha.nghodki.ai` via the front door) | HTTP/API `127.0.0.1:7880` and `[::1]:7880` only; ICE TCP `:7881`, UDP `:7882` |
| State (not in Git) | `/home/nikjetson/homeassistant/config` (restic) | none; the key comes from `secrets/voice.enc.yaml` |

The old hand-run compose file (`~/workspace/roboclaw/home-assistant/docker-compose.yml`) was renamed to
`docker-compose.yml.moved-to-homelab` so nobody brings `:stable` back by accident.

## Deploy

```bash
cd ~/homelab/hosts && source ~/.venvs/ansible/bin/activate
ansible-playbook playbooks/home.yml --check --diff      # always first
ansible-playbook playbooks/home.yml
```

- Home Assistant: the container is recreated only when the compose file changes (an image bump), about 30 s of
  downtime. After an upgrade, run the MCP drift check (runbooks/mcp-admission.md): new or renamed entities change
  the tool hashes.
- LiveKit: a changed key, config or version restarts the user unit. LiveKit refuses a key file others can read, so
  the config stays 0600.

## Check

```bash
# on the Jetson
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8123/         # HA: 200
curl -s -o /dev/null -w '%{http_code}\n' https://ha.nghodki.ai/        # HA via the front door: 200 (any client)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7880/        # LiveKit: 200 ("OK")
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8200/        # control center: 200
systemctl --user status livekit-server
```

A ListRooms call with the key from SOPS must return 200 (and 401 with a wrong key): see "ListRooms check" below.

## Upgrade

- Home Assistant: merge the Renovate PR (read the release notes for breaking changes), deploy, check, then the MCP
  drift check.
- LiveKit: set `livekit_version` and `livekit_tarball_sha256` (from the release's `checksums.txt`) together.

## Roll back

- Home Assistant: revert the compose change and deploy (restic has the config dir).
- LiveKit: set the previous version back; the old release folder stays in `/opt/livekit/`.

## ListRooms check

On the Jetson, as nikjetson: sign a 60-second token with the key in `livekit.yaml` (nothing is printed) and list
rooms. Expect `key: 200 | wrong secret: 401`.

```bash
python3 - <<'PY'
import time, urllib.request, urllib.error, jwt, yaml, pathlib
keys = yaml.safe_load(pathlib.Path.home().joinpath(".config/livekit/livekit.yaml").read_text())["keys"]
(k, s), = keys.items()
def call(secret):
    t = jwt.encode({"iss": k, "exp": int(time.time()) + 60, "video": {"roomList": True}}, secret, algorithm="HS256")
    r = urllib.request.Request("http://127.0.0.1:7880/twirp/livekit.RoomService/ListRooms", b"{}",
                               {"Authorization": "Bearer " + t, "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(r, timeout=10).status
    except urllib.error.HTTPError as e:
        return e.code
print("key:", call(s), "| wrong secret:", call("x" * 40))
PY
```
