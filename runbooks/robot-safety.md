# Robot safety governor (Pi)

Plan P5.2. A ROS 2 node on the Pi that sits between every command source and the motors and enforces,
without any agent or LLM, an **e-stop** (latched), **speed caps**, an **obstacle stop** from `/scan` and
**watchdogs** (heartbeat 2 s, command 0.5 s, `/scan` 1 s). Playbook: `hosts/playbooks/robot.yml` (play
"Safety governor", role `safety_governor`). Code: `robots/safety/governor/`. Limits: `robots/safety/limits.yaml`.

**As deployed, the governor drives a mock sink: it never sends anything to the motors.** A real sink is
enabled only for the on-blocks test below.

picoclaw (the robot's agent) runs as its own unprivileged user `picoclaw`, and its motion tools go through
the governor (via the motion bridge); see [picoclaw](#picoclaw-own-user-motion-through-the-governor). Hermes'
motion tools (Jetson) ask picoclaw to move over MQTT/NATS, so they go through the governor too; see
[Hermes](#hermes-jetson-motion-through-picoclaw). **Every agent motion path is governed**; what is left is
the car's firmware, which takes motion commands from anyone on the LAN (gap 2 below).

## How the robot is driven (updated 2026-11-15, all agent motion paths governed)

The car is an ESP32 with its own HTTP API (`firmware/roboclaw_firmware.ino` in the roboclaw project, not on
these hosts). Endpoints used: `POST /drive {direction, speed 0-255, duration_ms, avoid}`, `POST /turn
{direction, degrees}`, `POST /velocity {linear, angular}`, `POST /stop`, `POST /horn`, `POST /scan`,
`GET /status`, `GET /sensors`. Per the code, the firmware stops by itself when `/velocity` calls stop
for 500 ms, and does its own ultrasonic and IR-edge avoidance on forward `/drive` with `avoid: true`.

| Path | Who | How it reaches the motors | Through the governor? |
|---|---|---|---|
| 1 | picoclaw (system unit `picoclaw`, user `picoclaw`) | MCP server `picoclaw-hardware` (stdio, Pi `/var/lib/picoclaw/roboclaw/mcp-server/picoclaw-hardware-mcp.js`): tools `drive`, `turn`, `explore`, `go_to_room`, `follow_nearest`, `map_room` → motion bridge socket `/run/robot-motion/motion.sock` → `/cmd_vel_in` + `/safety/heartbeat`. `stop` latches the governor's e-stop and calls the car's `/stop`. `status`, `get_sensors`, `horn`, `scan_surroundings` still call the car's HTTP API (no motion). `navigate_to`, `explore_frontier` (Nav2) and `follow_start` (vision-ai follow-me) are disabled: they would drive around the governor | **Yes** (since 2026-11-15) |
| 1b | Hermes (Jetson, profile hermes-nikhil) | MCP server `picoclaw_only` (stdio, Jetson `/home/nikjetson/workspace/roboclaw/mcp-server/picoclaw-hardware-mcp.js`, patched by role `hermes_robot_mcp`): `drive`, `turn`, `explore`, `go_to_room`, `follow_nearest`, `map_room` send one structured request to picoclaw over MQTT/NATS (as user `hermes`, the topic of `send_to_picoclaw_agent`) → picoclaw's own tools → path 1. `send_to_picoclaw_agent` (free text) ends in picoclaw's tools too. `stop` latches the governor's e-stop over NATS (`robot.pi.safety.estop`) and calls the car's `/stop`. `navigate_to`, `explore_frontier`, `follow_start` are disabled. No `/drive`, `/turn` or `/velocity` call is left in the file (role and nightly drift check) | **Yes** (since 2026-11-15) |
| 2 | Nav2 (later, P5.3) | `/cmd_vel` → `cmd_vel_bridge` (Pi `~/workspace/roboclaw/ros2-nav`, Humble env `ros2_nav`, **not running**) → `POST /velocity` | **No** (it listens on `/cmd_vel`) |
| 3 | Jetson control-center backend | `POST /stop` only | n/a (stop only) |
| 4 | the governor | sink `http_velocity` (`POST /velocity`) or `ros_cmd_vel` (`/cmd_vel`) | it *is* the governor |

`roboclaw.local` does not resolve on the LAN (no mDNS alias), so paths 1 and 2 can't reach the car at
the moment either. Nothing on the Pi drives the motors directly (no serial or GPIO motor driver).

**Gaps that must be closed before the robot drives on its own:**
1. ~~Point the MCP server's motion tools at the governor~~ Done 2026-11-15 (motion bridge, below).
2. **Open: the car's firmware accepts motion from anyone on the LAN.** Give it one caller: only the governor's
   address (or a shared token) may call `/drive`, `/turn` and `/velocity`. Until then anything on the LAN can
   bypass the governor, including the agents' own shell or web tools (picoclaw's `exec`/`web_fetch`, Hermes'
   terminal on the Jetson, e.g. `curl http://<car>/drive`): no MCP server calls them any more, but the agents'
   network access isn't filtered. This is the only motion path left that isn't governed.
3. When Nav2 arrives, it publishes `/cmd_vel_in`, not `/cmd_vel`; don't run `cmd_vel_bridge` next to the
   governor's `http_velocity` sink. Then re-enable `navigate_to`/`explore_frontier` in the MCP patch.
4. ~~The Jetson's copy of the MCP server (`tools/picoclaw_only`, for Hermes) still calls `/drive`/`/turn`~~
   Done 2026-11-15: its motion tools go to picoclaw ([Hermes](#hermes-jetson-motion-through-picoclaw)). Hermes'
   `tools.include` (`send_to_picoclaw_agent`, `check_picoclaw_agent_connection`) is unchanged; it is no longer
   the only thing between Hermes and the car's motion API.

## Architecture

```
 Hermes MCP drive/turn/... ─MQTT/NATS─> picoclaw agent ─┐   Hermes MCP stop ─> NATS robot.pi.safety.estop
                                                       v
 picoclaw MCP drive/turn/... ─> /run/robot-motion/motion.sock ─> robot-motion-bridge ─> /cmd_vel_in + /safety/heartbeat

 /cmd_vel_in (Twist) ─┐                                    ┌─> sink: mock (default) | http_velocity → car /velocity
 /scan (LaserScan) ───┤   safety_governor (rclpy node)     │         | ros_cmd_vel → /cmd_vel
 /safety/estop Bool ──┤   core.Governor (pure Python):     ├─> /safety/status (std_msgs/String, JSON, 2 Hz)
 /safety/reset (off) ─┤   e-stop > scan > heartbeat >      ├─> NATS robot.pi.safety.status (JSON, 1 Hz + on change)
 /safety/heartbeat ───┤   command timeout > ceiling >      ├─> journal, SYSLOG_IDENTIFIER=safety-governor → Loki
 NATS robot.pi.safety.estop / .reset, robot.pi.cmd.heartbeat ┘ └─> 127.0.0.1:9113/metrics → host collector → VictoriaMetrics
```

- **Pure core** (`safety_governor/core.py`, no ROS/NATS): every input carries a monotonic timestamp and
  `step(now)` returns the allowed velocity. Order of precedence, first match wins:

  | # | Condition | Output | State |
  |---|---|---|---|
  | 1 | e-stop latched | zero | `estop` |
  | 2 | no `/scan` yet, last one older than `scan_timeout` (1 s), or under 20% valid ranges | zero | `fault` |
  | 3 | no heartbeat within `heartbeat_timeout` (2 s) | zero | `fault` |
  | 4 | no command within `cmd_timeout` (0.5 s) | zero | `idle` |
  | 5 | command not finite, or above the ceiling (0.5 m/s, 2.5 rad/s) | zero | `rejected` |
  | 6 | obstacle closer than `stop_distance` (0.35 m) within ±35° of the travel direction | translation zero, turning kept | `limited` |
  | 7 | above the caps (0.2 m/s, 1.0 rad/s) | clamped | `limited` |
  | 8 | otherwise | as commanded | `ok` |

  Sideways motion (`vy`) is forced to 0 (`allow_strafe: false`; `/velocity` has no strafe). The travel
  direction is `atan2(vy, vx)`, so reversing checks the sector behind: **reversing away from an obstacle
  is allowed**. Ranges that are inf/NaN, below `range_min` or below `self_filter_radius` (0.08 m, the
  robot's own body) are ignored. `lidar_yaw_deg` turns the LiDAR's angle 0 into the robot's forward
  (0 as mounted now; check it on blocks).
- **E-stop latch:** `/safety/estop` `true` or *any* message on `robot.pi.safety.estop` latches it.
  `/safety/estop false` does **not** clear it. Only `robot.pi.safety.reset` with payload `RESET` clears
  it, and commands received before the reset are dropped, so the robot doesn't move until a fresh command
  arrives.
- **Reset is human-only** (2026-11-15). Agents may latch the e-stop, never clear it:
  - NATS: `picoclaw` and `hermes` have a `deny` on `robot.pi.safety.reset` (and `robot.pi.safety.test.reset`);
    the server refuses the publish (`Publish Violation` in `docker logs bus-nats-1` on dgx-1, a
    `permissions violation` error to the client) and the message never reaches the governor. They keep
    `robot.pi.safety.estop`. Only the NATS user `operator` (and `admin`) may publish the reset subject; the
    `safety-reset` command uses it. The governor can't see who published, so the NATS permissions are the check.
  - ROS: `/safety/reset` is **off** (`ros.reset_enabled: false`, role variable
    `safety_governor_ros_reset_enabled`), because any node on the Zenoh network could publish it. The
    governor still listens and logs each attempt (`INTERVENTION kind=reset_refused ... reset from ros refused`).
    The pure core enforces it too: `Governor(config, reset_sources={"nats"})` refuses any other source.
  - picoclaw runs as its own user `picoclaw` (no sudo, login home closed), so it can't read the root-only
    operator file or the governor's files, or stop the governor (checked by the role on every run; below).
- **Fail safe:** zero is sent to the sink at 10 Hz in every non-moving state; on exit the node sends zero
  once more. If the node is down, nothing calls the car, and the firmware's 500 ms deadman stops it. The
  watchdogs don't latch: they clear when inputs come back.
- **Heartbeat:** the commanding side (Nav2 bridge, teleop, the motion bridge while a move runs) must send
  `std_msgs/Empty` on `/safety/heartbeat` or anything on `robot.pi.cmd.heartbeat`, at least every 2 s
  (5 Hz is a good rate). No heartbeat, no motion.
- **Transport:** ROS goes over Zenoh in client mode through the Jetson's router (runbooks/robot-ros.md),
  so if the Jetson or Wi-Fi drops, `/scan` and the heartbeats stop and the governor stops within 1–2 s.
  NATS (as user `picoclaw`) is only for e-stop, reset (received), heartbeat and status; losing NATS doesn't stop
  the robot (the other watchdogs do), but a NATS e-stop can't arrive then. Use the ROS e-stop as well.

## Files and config on the Pi

| What | Where |
|---|---|
| Unit | `~/.config/systemd/user/safety-governor.service` (`Restart=always`, after `ros-lidar`) |
| Code | `~/.local/lib/safety-governor/safety_governor/` |
| Config (rendered from `limits.yaml` + role vars) | `~/.config/safety-governor/governor.json` |
| NATS credentials (picoclaw, from SOPS `secrets/bus.enc.yaml`) | `~/.config/safety-governor/nats-credentials.json` (0600; dir 0700) |
| E-stop CLI | `~/.local/bin/safety-estop` (as picoclaw) |
| Reset CLI | `~/.local/bin/safety-reset` (as operator; also on dgx-1) |
| NATS credentials (operator, from SOPS `nats_operator_password`) | `/etc/safety-operator/nats-operator.json` (root, 0600; dir 0700), Pi and dgx-1 |
| Integration test | `~/.local/lib/safety-governor/run-integration-test` |
| Motion bridge: unit | `/etc/systemd/system/robot-motion-bridge.service` (system unit, as the login user, group `robot-motion`) |
| Motion bridge: code, config | `~/.local/lib/safety-governor/motion_bridge/`, `~/.config/safety-governor/motion-bridge.json` (code: `robots/safety/motion_bridge/`) |
| Motion bridge: socket | `/run/robot-motion/motion.sock` (dir 0750, socket 0660, group `robot-motion` = picoclaw) |
| Motion integration test | `~/.local/lib/safety-governor/run-motion-integration-test` |
| nats-py | `nats-py 2.14.0` (conda-forge) in env `ros2_kilted`, pinned by the role |

Role variables (`hosts/roles/safety_governor/defaults/main.yml`): `safety_governor_sink` (`mock`),
`safety_governor_real_sink_enabled` (`false`), `safety_governor_http_url` (empty),
`safety_governor_limit_overrides` (`{}`), `safety_governor_ros_reset_enabled` (`false`). To change a limit, edit `robots/safety/limits.yaml` (while the
robot is docked), open a PR, and run the playbook. The node refuses unknown keys and limits that
contradict each other (a cap above the ceiling, for example).

```bash
# from dgx-1, in the repo's hosts/ folder
source ~/.venvs/ansible/bin/activate
ansible-playbook playbooks/robot.yml --limit pi --check --diff
ansible-playbook playbooks/robot.yml --limit pi
```

## picoclaw (own user), motion through the governor

Playbook `hosts/playbooks/robot.yml` (play "PicoClaw (own user)", role `picoclaw`), after the governor play.

**The user.** System user `picoclaw` (uid 995 on the Pi), shell `nologin`, home `/var/lib/picoclaw`, groups
`picoclaw` and `robot-motion` only: no `sudo`, no `dialout` (picoclaw's serial/i2c/spi tools are off and the
MCP server uses no serial port), no `dclaw-ipc` (the DefenseClaw Lite hook loads its engine in-process and
never uses the Edge Connector's socket, runbooks/edge-connector.md). The login home is 0750, so picoclaw
can't read anything in it. The role checks on every run that `sudo -l -U picoclaw` says "not allowed" and
that `runuser -u picoclaw -- test -r` fails for `/etc/safety-operator/nats-operator.json` and the governor's
credentials, config, unit and code. Checked by hand 2026-11-15: `sudo -u picoclaw cat` on each →
`Permission denied`.

**Unit** `/etc/systemd/system/picoclaw.service` (`systemctl status picoclaw`, `journalctl -u picoclaw`):
`User=picoclaw`, `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=yes` (/home invisible), `PrivateTmp`,
`PrivateDevices`, no capabilities, `MemoryMax=1G`. Writable: `~/.picoclaw` and `~/.defenseclaw/logs` only;
`config.json` and `.security.yml` are read-only inside the unit, so the agent can't rewrite its own hook,
MCP server or model settings.

| What | Where (owner) |
|---|---|
| Binaries `picoclaw`, `node` | `/var/lib/picoclaw/bin/` (root, 0755) |
| Config, `.security.yml` (MQTT/NATS password, model keys), workspace, sessions, logs | `/var/lib/picoclaw/.picoclaw/` (picoclaw, 0700) |
| LiteLLM key (`OPENAI_API_KEY`) | `/etc/picoclaw/picoclaw.env` (root, 0600; read by systemd) |
| DefenseClaw Lite hook, engine, policy | `/var/lib/picoclaw/.defenseclaw/{bin,lib,policies}` (root:picoclaw, read-only); log `.defenseclaw/logs/dclaw_hook.log` (picoclaw) |
| MCP server `picoclaw-hardware` | `/var/lib/picoclaw/roboclaw/mcp-server/` (root:picoclaw, read-only); `governor-motion.js` from `hosts/roles/picoclaw/files/`; original `picoclaw-hardware-mcp.js.pre-governor` |
| Config path rewrite helper | `/usr/local/lib/picoclaw/picoclaw_paths.py` (paths only, never the secrets) |

The first run copied everything once from the login user (`~/.picoclaw`, `~/.defenseclaw`, `~/.local/bin/{picoclaw,node}`,
`~/.config/picoclaw/env`, `~/workspace/roboclaw/mcp-server`; marker `/var/lib/picoclaw/.migrated-from-nikghodki-raspberry-1`)
and pointed `config.json`'s workspace, hook and MCP paths at the new home. The NATS/MQTT credentials and the
LiteLLM key are unchanged. After the move (2026-11-15): NATS `connz?auth=1` on dgx-1 shows `picoclaw`, MQTT client
`picoclaw-pi`, reconnected at 01:41:30Z; `dclaw_hook.log`: `Loading libdclaw from /var/lib/picoclaw/.defenseclaw/lib/libdclaw_core.so`,
`DefenseClaw Lite engine initialized`.

**The roboclaw code is not a git repository** (Pi `~/workspace/roboclaw`, dgx-1 `~/workspace/roboclaw/dgx`, Jetson
copy for Hermes): there was no repo to commit to. The change to the user's `picoclaw-hardware-mcp.js` is the patch
`hosts/roles/picoclaw/files/picoclaw-hardware-mcp.governed.patch`, applied by the role (`ansible.posix.patch`, idempotent);
the role fails if any `post("/drive" | "/turn" | "/velocity")` is left. If roboclaw becomes a repo, commit the patched file
there and drop the patch.

**Motion path.** The MCP server's motion tools send one JSON request per call to the motion bridge's Unix socket
(`governor-motion.js`); the bridge (`robots/safety/motion_bridge/`, ROS 2 node in `ros2_kilted`, unit
`robot-motion-bridge`) publishes `geometry_msgs/Twist` on `/cmd_vel_in` at 10 Hz and `std_msgs/Empty` on
`/safety/heartbeat` at 5 Hz (reliable, depth 10, as the governor subscribes) for the move's duration, then one zero
Twist, and answers with what the governor did (from `/safety/status`: moved, clamped, blocked and why). Why this and
not NATS: the governor's command input is ROS; a local socket needs no new subject or permissions and keeps working
when dgx-1 is down, and the socket's group decides who may command motion.
- `drive`: speed 0–255 scales to 0–0.4 m/s or 0–2.0 rad/s (above the caps, so the governor clamps; below the
  ceiling, so it never rejects); `duration_ms` default 1000, max 10000; strafing refused; `avoid` ignored (the
  governor's LiDAR stop is always on). `turn`: 0.8 rad/s for the angle. A blocked move is a tool error.
- No request, no heartbeat: between moves the governor sits in `fault/heartbeat_timeout`.
- A move is refused before anything is published if the governor's e-stop is latched or no status came for 2 s.
- `stop` (tool) → bridge `stop`: zero Twist and `/safety/estop true` (latched; **clearing needs `safety-reset`, a
  human**), plus the car's `/stop`. The task tools end with `halt` (zero, no latch) plus the car's `/stop`.
- Every request is one journal line: `journalctl -t robot-motion-bridge` → `MOTION op=drive uid=995 ... result=...`.

**Rollback** (back to picoclaw as the login user, ungoverned motion):
```bash
# on the Pi
sudo systemctl disable --now picoclaw
systemctl --user enable --now picoclaw-gateway   # old unit, old ~/.picoclaw and old MCP server (direct HTTP motion)
chmod 0775 ~                                     # only if something needs the old home mode
# the bridge can stay; to remove it too: sudo systemctl disable --now robot-motion-bridge
```
The role stops and disables the old user unit on every run, so don't run `robot.yml` after a rollback until this
change is reverted in the repo. Nothing was deleted: the old files and unit are still in the login home.

## Hermes (Jetson), motion through picoclaw

Playbook `hosts/playbooks/robot.yml` (play "Hermes robot MCP (motion via PicoClaw)", role `hermes_robot_mcp`, host
`jetson`). Hermes' profile hermes-nikhil runs nikjetson's copy of the same MCP server as `picoclaw_only`
(runbooks/hermes-profiles.md). The roboclaw folder isn't a git repository, so the change is the patch
`hosts/roles/hermes_robot_mcp/files/picoclaw-hardware-mcp.hermes.patch`, like picoclaw's on the Pi.

**Why through picoclaw (option A), not a governed API on the Pi (option B).** Hermes already reaches picoclaw: the
MCP server is connected to NATS' MQTT port as user `hermes`, which may publish `/.picoclaw.>` and `robot.>`, and
picoclaw's tools already go through the governor. Option A needs no new service, port, credential or NATS
permission. Option B would need a new authenticated listener on the Pi, and the Tailscale/LAN policy only lets the
robot talk to dgx-1. With A there is one motion path into the robot (picoclaw's MCP server → motion bridge →
governor), and one place to audit it (`journalctl -t robot-motion-bridge`).

**What the patched copy does.**
- `drive`, `turn`, `explore`, `go_to_room`, `follow_nearest`, `map_room`: one message on `/picoclaw/robot/hermes/request`
  (the topic `send_to_picoclaw_agent` uses), first line `[hermes-motion v1] {"tool": ..., "arguments": {...}}`, then an
  instruction to call that tool once and answer `{"ok": true, "result": ...}` or `{"ok": false, "error": ...}`. A reply
  with `ok: false` (refused, blocked by the governor, e-stop) is a tool error; no answer within 120 s is an error too.
  picoclaw runs the move with its governed tools, so the caps, the obstacle stop, the watchdogs and the e-stop apply.
- `stop`: publishes on MQTT `robot/pi/safety/estop` = NATS `robot.pi.safety.estop` (latched; **clearing needs
  `safety-reset`, a human**) and calls the car's `/stop`. It doesn't wait for picoclaw or its model.
- `navigate_to`, `explore_frontier` (Nav2) and `follow_start` (vision-ai follow-me) are disabled, as on the Pi.
- `status`, `get_sensors`, `horn`, `scan_surroundings`, `find_path` still call the car's HTTP API (no motion).
- The original is kept as `picoclaw-hardware-mcp.js.pre-governor`. The launch is unchanged (same Node, same path), so
  the DefenseClaw registry entry is too; the 10 changed tool definitions are in `tools/picoclaw_only`.

**Guards.** The role refuses a file that is neither the reviewed original nor the patched file (sha256 in
`roles/hermes_robot_mcp/defaults`), fails if `grep -E` finds a direct motion call after patching, and checks the
patched sha256. The pattern lives in `policies/defenseclaw/mcp-servers.yaml` (`drift_check.picoclaw_only.forbidden_source`):
any `"/drive"`, `"/turn"`, `"/velocity"` or `"/follow/start"` string, `ros2 action send_goal /` or `ros2 launch explore_lite`.
The nightly mcp-drift check applies the same pattern to the live file (`mcp-drift.source`, `change: forbidden_call`;
runbooks/mcp-admission.md), and CI checks that the patch removes every match (`hosts/roles/mcp_drift/files/tests`).
It is a tripwire against reverts and copy-paste, not a proof: nikjetson owns the file and can edit it (the hash
changes the tool definitions only if the descriptions change), and gap 2 above is still open.

When the role changes the file, its handler restarts `hermes-gateway` of hermes-nikhil (Hermes starts MCP servers
only at start). After the change (2026-11-15): Hermes' log `MCP server 'picoclaw_only' (stdio): registered 2 tool(s)`,
`mcp-stderr.log` `motion via PicoClaw + safety governor, e-stop: robot/pi/safety/estop`; a check on the bus with the
test topic `robot/pi/safety/test/estop` as `hermes` arrived as NATS `robot.pi.safety.test.estop` (the deployed governor
listens only on `robot.pi.safety.estop`).

**Rollback** (Hermes' copy back to direct HTTP motion; the include list still hides those tools):
```bash
# on the Jetson, as nikjetson
cp -a ~/workspace/roboclaw/mcp-server/picoclaw-hardware-mcp.js.pre-governor ~/workspace/roboclaw/mcp-server/picoclaw-hardware-mcp.js
setfacl -m u:hermes-nikhil:r ~/workspace/roboclaw/mcp-server/picoclaw-hardware-mcp.js
sudo -u hermes-nikhil XDG_RUNTIME_DIR=/run/user/$(id -u hermes-nikhil) systemctl --user restart hermes-gateway
```
Then revert the tool hashes in `tools/picoclaw_only` (or the nightly drift check reports 10 changed tools and a
forbidden call), and don't run `robot.yml` on the Jetson until the role is reverted too.

## E-stop

One line, from the Pi (NATS, as picoclaw) or dgx-1 (NATS, as operator):

```bash
safety-estop                 # latch; prints the governor's status (state "estop")
safety-estop status
safety-reset                 # clear (RESET as operator; exits 0 once the governor reports it clear)
```

`safety-reset` reads the operator password with `sudo -n cat /etc/safety-operator/nats-operator.json` and
passes it on stdin (`estop_cli --credentials -`), never on a command line. On the Pi, `safety-estop reset`
runs `safety-reset`. On dgx-1 both commands are in `~/.local/bin`, with nats-py in
`~/.local/share/safety-cli/venv` (hash-locked, `roles/safety_governor/files/requirements-cli.txt`), installed by
`playbooks/bus.yml` (play "Operator safety CLI", `tasks/operator_cli.yml`).

From the Pi or the Jetson (ROS; works without NATS). Latching only: a ROS reset is refused.

```bash
ros2-kilted topic pub --once /safety/estop std_msgs/msg/Bool "{data: true}"
```

From any NATS client with `robot.pi.>` publish rights (picoclaw, hermes; homelab CA):
`nats pub robot.pi.safety.estop stop --server tls://nats.nghodki.ai:4222 --tlsca homelab-ca.crt --user picoclaw --password …`.
Any payload latches. Reset needs the exact payload `RESET` on `robot.pi.safety.reset`, as `operator`.

Rotate the operator password: new value and bcrypt hash (`$2a$`, cost 10, python `bcrypt` in the Ansible venv)
in `secrets/bus.enc.yaml` (`sops set --value-stdin`), then `playbooks/bus.yml` (NATS restarts for a moment;
clients reconnect) and `playbooks/robot.yml --limit pi`.

Check (mock sink only), 2026-11-15: e-stop as picoclaw latched; RESET as picoclaw and as hermes refused
(`Publish Violation`, still latched); `safety-reset` on dgx-1 and on the Pi cleared it; the integration test's
ROS reset was refused (22/22 checks).

## Status, logs and alerts

- `ros2-kilted topic echo /safety/status` or `safety-estop status`: JSON with `state`, `reason`, `detail`,
  `estop`, `last_stop` (the last reason it stopped the robot), the input ages, the nearest obstacle per
  quadrant (`nearest_m.front/left/back/right`), the intervention counts, the sink and the limits.
- Journal: `journalctl -t safety-governor -f` on the Pi. The Pi's host collector ships the journal to
  Loki; the identifier is a field in the JSON body, not a label:
  `{host_name="nikghodki-raspberry"} |= "INTERVENTION" | json ident="SYSLOG_IDENTIFIER", msg="MESSAGE" | ident="safety-governor" | line_format "{{.msg}}"`
  (checked 2026-11-15: the deploy check's e-stop shows up there). Every intervention is one line (`kind=intervention|estop|reset reason=… detail=…`),
  logged once each time the reason changes, not on every tick. The integration test's instance logs as
  `safety-governor-test`.
- Metrics, `curl -s 127.0.0.1:9113/metrics` on the Pi: `safety_governor_status_timestamp_seconds`,
  `_estop_latched`, `_state{state}`, `_scan_age_seconds`, `_nats_connected`, `_real_sink`,
  `_interventions_total{reason}`. The Pi's host collector scrapes them (job `safety-governor`,
  `hosts/host_vars/pi.yml`).
- vmalert (`hosts/stacks/observe/vmalert/rules/robot.yml`) → Alertmanager → ntfy:
  - **SafetyGovernorStatusStale** (critical): no status published for 60 s, or no metric for 3 min, for 2 min.
  - **SafetyGovernorLidarStale** (warning): no `/scan` for over 5 s, for 5 min.
  - **SafetyGovernorRealSinkEnabled** (warning): a real sink active for 2 h (it was left on after a test).

  Why a metric: the timestamp is set only when a status message is actually published, so it covers
  "process dead" (scrape fails → series absent) and "process hung" (value stops moving). The status JSON
  on NATS or a journal line in Loki would need a new NATS consumer or Loki ruler rules; the host
  collector and vmalert were already there.

## Tests

- **Unit** (CI, `pr-checks` → checks, standard library + pytest):
  `cd robots/safety/governor && PYTHONPATH=. python -m pytest -q tests`. They cover the e-stop latch and
  reset, clamping, the ceiling, the obstacle sector (edges, reversing, strafing, LiDAR yaw, the real MS200
  geometry, invalid ranges), the watchdogs, stale/invalid scans, the order of precedence and the sinks.
- **On the Pi** (mock sink only): `~/.local/lib/safety-governor/run-integration-test`. It starts a
  throw-away governor in ROS domain 73 (fake `/scan` never reaches domain 0, where the real LiDAR and
  the deployed governor are) on NATS subjects `robot.pi.safety.test.*`, publishes fake `/scan` (obstacle
  at 0.2 m ahead or clear), `/cmd_vel_in` and heartbeats, sends e-stops over NATS as picoclaw and over
  ROS, stops the heartbeat, the scan and the commands, and checks the mock sink's log. 22 checks, about
  25 s; exit 0 when all pass. It refuses to run without `ROS_DOMAIN_ID=73` (the wrapper sets it).
- **Motion path on the Pi** (mock sink only): `~/.local/lib/safety-governor/run-motion-integration-test`. Domain 73
  again: a throw-away governor (mock sink, NATS off), a throw-away bridge on a socket in a temp folder, fake `/scan`,
  a fake car on 127.0.0.1 that records every request, and picoclaw's real MCP server run as `picoclaw` (`sudo -u`).
  It calls `drive` forward at speed 255 (mock sink gets vx 0.2 = the cap, from 0.4 commanded), checks the motion ends
  with the call and the heartbeat stops, `turn`, a refused strafe, `drive` with an obstacle 0.2 m ahead (blocked) and
  backwards (allowed), `explore`, `stop` (governor e-stop latched + car `/stop`), `drive` during the e-stop (blocked),
  that the car never got `/drive`, `/turn` or `/velocity`, and that nothing exceeded the caps. 15 checks, about 30 s.
  2026-11-15: 15/15 (car saw only `/status` and `/stop`); the governor test 22/22. The `zenoh ... Unknown token` errors
  printed at the end are rmw_zenoh shutdown noise. Bridge unit tests: CI (`robots/safety/motion_bridge/tests`).
- **Hermes' motion path on the Pi** (mock sink only): `~/.local/lib/safety-governor/run-hermes-motion-integration-test`.
  The same domain-73 harness (test governor and bridge, fake `/scan`), plus: Hermes' MCP copy built from the login
  user's original roboclaw MCP folder with role `hermes_robot_mcp`'s patch (the sha256 must equal the Jetson's), a
  minimal MQTT broker on 127.0.0.1 in place of NATS' MQTT port (no real broker, no credentials), a stand-in for the
  picoclaw agent without its model (it runs Hermes' structured request with picoclaw's real MCP server as `picoclaw`;
  it also hands the test e-stop topic to the governor as `/safety/estop`, which is what NATS does in production), and
  one fake car per MCP server. Checks: Hermes `drive` forward at 255 → mock sink vx 0.2 (the cap), ends with the call;
  `turn`; strafe refused; obstacle blocked; Nav2/follow-me refused without reaching picoclaw; `stop` → e-stop on the
  e-stop topic, governor latched, car `/stop`; `drive` during the e-stop blocked; no `/drive`, `/turn`, `/velocity` at
  either car (Hermes' car saw only `/stop`); nothing above the caps. 15 checks, about 30 s. 2026-11-15: 15/15; the
  governor test 22/22 and the motion test 15/15 again after redeploying. The model's own handling of the request (does
  picoclaw call the tool it is asked to) is not covered: the test has no LLM.

## "Robot on blocks" test (for you)

Do this before the governor drives the real car for the first time, after any change to limits or code,
and as gate 2 of a policy rollout (architecture §15.5). The car must be **on blocks with all wheels off
the ground** for the whole test.

### Before

1. Car on blocks, wheels free, nothing touching them. Battery charged. Hand on the car's power switch
   (the physical kill) for the whole test.
2. Find the car's IP (router DHCP list or its serial console); `roboclaw.local` doesn't resolve. Check
   it answers: `curl -s http://<car-ip>/status`.
3. Make sure nothing else drives the car during the test: stop picoclaw (`sudo systemctl stop picoclaw`; its moves
   go through the governor now, but you don't want an agent commanding during the test), and check
   `cmd_vel_bridge` isn't running (`pgrep -fa cmd_vel_bridge` on the Pi: nothing).
4. On the Pi: `systemctl --user is-active ros-lidar safety-governor` → both `active`;
   `systemctl is-active robot-motion-bridge` → `active`;
   `safety-estop status` → `"sink": {"kind": "mock", "real": false}`.
5. Run the integration tests once: `~/.local/lib/safety-governor/run-integration-test` → `22/22 checks passed`;
   `~/.local/lib/safety-governor/run-motion-integration-test` → `15/15 checks passed`;
   `~/.local/lib/safety-governor/run-hermes-motion-integration-test` → `15/15 checks passed`.

### Enable the real sink, only for this test

From dgx-1, in `hosts/` (nothing is committed; the variables live only on the command line):

```bash
ansible-playbook playbooks/robot.yml --limit pi --diff \
  -e safety_governor_sink=http_velocity -e safety_governor_real_sink_enabled=true \
  -e safety_governor_http_url=http://<car-ip>
```

On the Pi: `journalctl -t safety-governor -n 5` → `sink http_velocity (real=True)`; `safety-estop status`
→ `"real": true`. From now on the governor sends `POST /velocity` at 10 Hz (zero while it isn't
commanded). The wheels must not turn yet: state is `fault` (no heartbeat).

Open two terminals on the Pi. In both: `export PATH=$HOME/.local/bin:$PATH`.

- Terminal A (heartbeat, keep running): `ros2-kilted topic pub -r 5 /safety/heartbeat std_msgs/msg/Empty "{}"`
- Terminal B: the commands below. Watch `ros2-kilted topic echo /safety/status` in a third one if you like.

### Check 1: e-stop

1. B: `ros2-kilted topic pub -r 10 /cmd_vel_in geometry_msgs/msg/Twist "{linear: {x: 0.1}}"`.
   **Expect:** the wheels turn forward slowly; status `ok`.
2. Another shell: `safety-estop`. **Expect:** the wheels stop within 0.2 s; status `estop`, `latched by nats`;
   journal `INTERVENTION kind=estop`. The command in B keeps running, the wheels stay still.
3. `ros2-kilted topic pub --once /safety/estop std_msgs/msg/Bool "{data: false}"`. **Expect:** still stopped.
4. `safety-reset`. **Expect:** the wheels turn again (B is still sending fresh commands).
5. Repeat 2–4 with the ROS e-stop (`/safety/estop true`, then `safety-reset`; `/safety/reset true` is refused). Same result.
6. Stop B (Ctrl-C). **Expect:** the wheels stop within 0.5 s (command timeout).

### Check 2: speed cap

1. B: `ros2-kilted topic pub -r 10 /cmd_vel_in geometry_msgs/msg/Twist "{linear: {x: 0.4}}"`.
   **Expect:** the wheels turn at the 0.2 m/s cap (the same speed as `x: 0.2`, compare by eye or with a
   tachometer); status `limited`, reason `clamped`.
2. B: `... "{angular: {z: 2.0}}"`. **Expect:** spin at the 1.0 rad/s cap; `clamped`.
3. B: `... "{linear: {x: 0.8}}"` (above the 0.5 m/s ceiling). **Expect:** wheels **stop**; status
   `rejected`, reason `above_ceiling`.
4. Stop B.

### Check 3: obstacle stop

1. B: `... "{linear: {x: 0.1}}"`. Wheels turn forward.
2. Hold a box or board **in front of the LiDAR** at about 25 cm (closer than 0.35 m). **Expect:** the
   wheels stop; status `limited`, reason `obstacle`, `nearest_m.front` about 0.25. If instead
   `nearest_m.left/right/back` shows 0.25, the LiDAR's forward is off: set `lidar_yaw_deg` in
   `robots/safety/limits.yaml` (90 = LiDAR's 0 points left) and redo this check.
3. Keep the board there. B: `... "{linear: {x: -0.1}}"`. **Expect:** the wheels turn **backwards**
   (reversing away is allowed).
4. B: `... "{linear: {x: 0.1}, angular: {z: 0.5}}"`. **Expect:** spin only, no forward motion.
5. Move the board behind the car at 25 cm, B: `... "{linear: {x: -0.1}}"`. **Expect:** stop.
6. Take the board away, B: `... "{linear: {x: 0.1}}"`. **Expect:** forward again. Stop B.

### Check 4: watchdog

1. B: `... "{linear: {x: 0.1}}"`. Wheels turn.
2. Stop terminal A (the heartbeat). **Expect:** the wheels stop about 2 s later; status `fault`, reason
   `heartbeat_timeout`. Restart A: the wheels turn again.
3. On the Pi: `systemctl --user stop ros-lidar`. **Expect:** the wheels stop within about 1 s; status
   `fault`, `scan_stale`. `systemctl --user start ros-lidar`: they turn again after the LiDAR is back
   (a few seconds). This stops the LiDAR only for this check.
4. `systemctl --user stop safety-governor`. **Expect:** the wheels stop within about 0.5 s (the governor
   sends zero on exit; otherwise the firmware's deadman). `systemctl --user start safety-governor`:
   state `fault` until it has a scan, then moving again because A and B are still running.
5. Stop B and A.

### Check 5: picoclaw's path (motion bridge)

Stop terminals A and B first (the bridge sends its own heartbeat while it moves). With the governor clear
(`safety-reset` if needed):

1. Send one request to the bridge, as picoclaw would (from the Pi):
   `sudo -u picoclaw python3 -c 'import socket;s=socket.socket(socket.AF_UNIX);s.connect("/run/robot-motion/motion.sock");s.sendall(b"{\"op\":\"drive\",\"direction\":\"forward\",\"speed\":100,\"duration_ms\":1500}\n");print(s.makefile().readline())'`.
   **Expect:** the wheels turn forward slowly for 1.5 s, then stop; the answer has `"moved": true`.
2. The same with `"speed":255`. **Expect:** no faster than the 0.2 m/s cap; `"clamped": true`.
3. Board in front at 25 cm, the same request. **Expect:** no motion; `"blocked": true, "blocked_reason": "obstacle"`.
4. `{"op":"stop"}`. **Expect:** status `estop` (`latched by ros`); the step-1 request now answers
   `"blocked_reason": "estop"` and the wheels stay still. `safety-reset` to clear.
5. Optional, end to end: `sudo systemctl start picoclaw` and ask it (MQTT) to drive forward for a second: same as 1.
   Ask it to stop: e-stop latched as in 4.

### After: back to the mock sink

```bash
ansible-playbook playbooks/robot.yml --limit pi --diff     # no -e: sink mock, real_sink_enabled false
```

On the Pi: `safety-estop status` → `"real": false`; `sudo systemctl start picoclaw` if you stopped it. Write down the results (date, commit, pass/fail per
check, any limit changed) in the PR or issue for the change you tested. If a check failed, leave the
real sink off and open an issue.

## Troubleshooting

- `state: fault, reason: scan_stale` with the LiDAR running: check `ros2-kilted topic hz /scan` on the Pi
  and the Zenoh router on the Jetson (runbooks/robot-ros.md).
- `nats_connected: false`: `journalctl -t safety-governor | grep NATS`; NATS runs on dgx-1
  (`nats.nghodki.ai:4222`). The robot stays safe; only the NATS e-stop is unavailable. Use the ROS e-stop.
- The unit restarts every 2 s: `journalctl --user -u safety-governor` (the Zenoh router must be up at
  start; with no router the node exits and systemd retries).
