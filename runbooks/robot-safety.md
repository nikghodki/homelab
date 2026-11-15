# Robot safety governor (Pi)

Plan P5.2. A ROS 2 node on the Pi that sits between every command source and the motors and enforces,
without any agent or LLM, an **e-stop** (latched), **speed caps**, an **obstacle stop** from `/scan` and
**watchdogs** (heartbeat 2 s, command 0.5 s, `/scan` 1 s). Playbook: `hosts/playbooks/robot.yml` (play
"Safety governor", role `safety_governor`). Code: `robots/safety/governor/`. Limits: `robots/safety/limits.yaml`.

**As deployed, the governor drives a mock sink: it never sends anything to the motors.** A real sink is
enabled only for the on-blocks test below.

## How the robot is driven today (2026-11-15)

The car is an ESP32 with its own HTTP API (`firmware/roboclaw_firmware.ino` in the roboclaw project, not on
these hosts). Endpoints used: `POST /drive {direction, speed 0-255, duration_ms, avoid}`, `POST /turn
{direction, degrees}`, `POST /velocity {linear, angular}`, `POST /stop`, `POST /horn`, `POST /scan`,
`GET /status`, `GET /sensors`. Per the code, the firmware stops by itself when `/velocity` calls stop
for 500 ms, and does its own ultrasonic and IR-edge avoidance on forward `/drive` with `avoid: true`.

| Path | Who | How it reaches the motors | Through the governor? |
|---|---|---|---|
| 1 | picoclaw (`picoclaw-gateway`) | MCP server `picoclaw-hardware` (stdio, Pi `~/workspace/roboclaw/mcp-server/picoclaw-hardware-mcp.js`): tools `drive`, `turn`, `stop`, `explore`, `go_to_room`, `follow_nearest`, `map_room` → HTTP to `ROBOCLAW_API` (`http://roboclaw.local`) `/drive`, `/turn` | **No** |
| 2 | Nav2 (later, P5.3) | `/cmd_vel` → `cmd_vel_bridge` (Pi `~/workspace/roboclaw/ros2-nav`, Humble env `ros2_nav`, **not running**) → `POST /velocity` | **No** (it listens on `/cmd_vel`) |
| 3 | Jetson control-center backend | `POST /stop` only | n/a (stop only) |
| 4 | the governor | sink `http_velocity` (`POST /velocity`) or `ros_cmd_vel` (`/cmd_vel`) | it *is* the governor |

`roboclaw.local` does not resolve on the LAN (no mDNS alias), so paths 1 and 2 can't reach the car at
the moment either. Nothing on the Pi drives the motors directly (no serial or GPIO motor driver).

**Gap that must be closed before the robot drives on its own** (not done here; picoclaw and its MCP
server were left untouched):
1. Point the MCP server's motion tools at the governor: publish `geometry_msgs/Twist` on `/cmd_vel_in`
   (plus a heartbeat) instead of calling `/drive` and `/turn`. Keep `stop` calling `/stop` directly, as a
   second stop path.
2. Give the car's firmware one caller: only the governor's address (or a shared token) may call
   `/drive`, `/turn` and `/velocity`. Until then anything on the LAN can bypass the governor.
3. When Nav2 arrives, it publishes `/cmd_vel_in`, not `/cmd_vel`; don't run `cmd_vel_bridge` next to the
   governor's `http_velocity` sink.

## Architecture

```
 /cmd_vel_in (Twist) ─┐                                    ┌─> sink: mock (default) | http_velocity → car /velocity
 /scan (LaserScan) ───┤   safety_governor (rclpy node)     │         | ros_cmd_vel → /cmd_vel
 /safety/estop Bool ──┤   core.Governor (pure Python):     ├─> /safety/status (std_msgs/String, JSON, 2 Hz)
 /safety/reset Bool ──┤   e-stop > scan > heartbeat >      ├─> NATS robot.pi.safety.status (JSON, 1 Hz + on change)
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
  `/safety/estop false` does **not** clear it. Only `/safety/reset` `true` or `robot.pi.safety.reset` with
  payload `RESET` clears it, and commands received before the reset are dropped, so the robot doesn't
  move until a fresh command arrives.
- **Fail safe:** zero is sent to the sink at 10 Hz in every non-moving state; on exit the node sends zero
  once more. If the node is down, nothing calls the car, and the firmware's 500 ms deadman stops it. The
  watchdogs don't latch: they clear when inputs come back.
- **Heartbeat:** the commanding side (Nav2 bridge, teleop, the MCP server once it's rewired) must send
  `std_msgs/Empty` on `/safety/heartbeat` or anything on `robot.pi.cmd.heartbeat`, at least every 2 s
  (5 Hz is a good rate). No heartbeat, no motion.
- **Transport:** ROS goes over Zenoh in client mode through the Jetson's router (runbooks/robot-ros.md),
  so if the Jetson or Wi-Fi drops, `/scan` and the heartbeats stop and the governor stops within 1–2 s.
  NATS (as user `picoclaw`) is only for e-stop, reset, heartbeat and status; losing NATS doesn't stop
  the robot (the other watchdogs do), but a NATS e-stop can't arrive then. Use the ROS e-stop as well.

## Files and config on the Pi

| What | Where |
|---|---|
| Unit | `~/.config/systemd/user/safety-governor.service` (`Restart=always`, after `ros-lidar`) |
| Code | `~/.local/lib/safety-governor/safety_governor/` |
| Config (rendered from `limits.yaml` + role vars) | `~/.config/safety-governor/governor.json` |
| NATS credentials (picoclaw, from SOPS `secrets/bus.enc.yaml`) | `~/.config/safety-governor/nats-credentials.json` (0600; dir 0700) |
| E-stop CLI | `~/.local/bin/safety-estop` |
| Integration test | `~/.local/lib/safety-governor/run-integration-test` |
| nats-py | `nats-py 2.14.0` (conda-forge) in env `ros2_kilted`, pinned by the role |

Role variables (`hosts/roles/safety_governor/defaults/main.yml`): `safety_governor_sink` (`mock`),
`safety_governor_real_sink_enabled` (`false`), `safety_governor_http_url` (empty),
`safety_governor_limit_overrides` (`{}`). To change a limit, edit `robots/safety/limits.yaml` (while the
robot is docked), open a PR, and run the playbook. The node refuses unknown keys and limits that
contradict each other (a cap above the ceiling, for example).

```bash
# from dgx-1, in the repo's hosts/ folder
source ~/.venvs/ansible/bin/activate
ansible-playbook playbooks/robot.yml --limit pi --check --diff
ansible-playbook playbooks/robot.yml --limit pi
```

## E-stop

One line, from the Pi (NATS, as picoclaw):

```bash
safety-estop                 # latch; prints the governor's status (state "estop")
safety-estop reset           # clear (sends RESET)
safety-estop status
```

From the Pi or the Jetson (ROS; works without NATS):

```bash
ros2-kilted topic pub --once /safety/estop std_msgs/msg/Bool "{data: true}"
ros2-kilted topic pub --once /safety/reset std_msgs/msg/Bool "{data: true}"
```

From any NATS client with `robot.pi.>` publish rights (picoclaw, hermes; homelab CA):
`nats pub robot.pi.safety.estop stop --server tls://nats.nghodki.ai:4222 --tlsca homelab-ca.crt --user picoclaw --password …`.
Any payload latches. Reset needs the exact payload `RESET` on `robot.pi.safety.reset`.

Note: every account that may publish `robot.pi.>` (picoclaw, hermes) may also *reset*. To make reset
human-only, tighten the NATS permissions in `hosts/stacks/bus/nats/` (deny `robot.pi.safety.reset` to
the agent accounts and give it a separate operator user). That's a follow-up.

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

- **Unit** (CI, `pr-checks` → unit-tests, standard library + pytest):
  `cd robots/safety/governor && PYTHONPATH=. python -m pytest -q tests`. They cover the e-stop latch and
  reset, clamping, the ceiling, the obstacle sector (edges, reversing, strafing, LiDAR yaw, the real MS200
  geometry, invalid ranges), the watchdogs, stale/invalid scans, the order of precedence and the sinks.
- **On the Pi** (mock sink only): `~/.local/lib/safety-governor/run-integration-test`. It starts a
  throw-away governor in ROS domain 73 (fake `/scan` never reaches domain 0, where the real LiDAR and
  the deployed governor are) on NATS subjects `robot.pi.safety.test.*`, publishes fake `/scan` (obstacle
  at 0.2 m ahead or clear), `/cmd_vel_in` and heartbeats, sends e-stops over NATS as picoclaw and over
  ROS, stops the heartbeat, the scan and the commands, and checks the mock sink's log. 20 checks, about
  25 s; exit 0 when all pass. It refuses to run without `ROS_DOMAIN_ID=73` (the wrapper sets it).

## "Robot on blocks" test (for you)

Do this before the governor drives the real car for the first time, after any change to limits or code,
and as gate 2 of a policy rollout (architecture §15.5). The car must be **on blocks with all wheels off
the ground** for the whole test.

### Before

1. Car on blocks, wheels free, nothing touching them. Battery charged. Hand on the car's power switch
   (the physical kill) for the whole test.
2. Find the car's IP (router DHCP list or its serial console); `roboclaw.local` doesn't resolve. Check
   it answers: `curl -s http://<car-ip>/status`.
3. Make sure nothing else drives the car during the test: don't ask picoclaw to move (its MCP tools
   call the car directly and bypass the governor), and check `cmd_vel_bridge` isn't running
   (`pgrep -fa cmd_vel_bridge` on the Pi: nothing).
4. On the Pi: `systemctl --user is-active ros-lidar safety-governor` → both `active`;
   `safety-estop status` → `"sink": {"kind": "mock", "real": false}`.
5. Run the integration test once: `~/.local/lib/safety-governor/run-integration-test` → `20/20 checks passed`.

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
4. `safety-estop reset`. **Expect:** the wheels turn again (B is still sending fresh commands).
5. Repeat 2–4 with the ROS e-stop (`/safety/estop true`, then `/safety/reset true`). Same result.
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

### After: back to the mock sink

```bash
ansible-playbook playbooks/robot.yml --limit pi --diff     # no -e: sink mock, real_sink_enabled false
```

On the Pi: `safety-estop status` → `"real": false`. Write down the results (date, commit, pass/fail per
check, any limit changed) in the PR or issue for the change you tested. If a check failed, leave the
real sink off and open an issue.

## Troubleshooting

- `state: fault, reason: scan_stale` with the LiDAR running: check `ros2-kilted topic hz /scan` on the Pi
  and the Zenoh router on the Jetson (runbooks/robot-ros.md).
- `nats_connected: false`: `journalctl -t safety-governor | grep NATS`; NATS runs on dgx-1
  (`nats.nghodki.ai:4222`). The robot stays safe; only the NATS e-stop is unavailable. Use the ROS e-stop.
- The unit restarts every 2 s: `journalctl --user -u safety-governor` (the Zenoh router must be up at
  start; with no router the node exits and systemd retries).
