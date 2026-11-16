---
title: "ROS 2 and Zenoh"
description: "ROS 2 Kilted with rmw_zenoh: the Zenoh router on the Jetson, the MS200 LiDAR node on the Pi, versions, measured /scan rate, and known issues."
---

Plan P5.1, runbooks/robot-ros.md, `hosts/playbooks/robot.yml`. Nothing here moves the robot: the only nodes are the
LiDAR driver and a static transform.

| Piece | Where | Managed by |
|---|---|---|
| Zenoh router `rmw_zenohd`, `tcp/[::]:7447` | Jetson, system unit `ros-zenoh-router.service` → container `ros-zenoh-router`, host network | role `ros_zenoh_router` |
| Router image `homelab/ros-zenoh:kilted-1` | built on the Jetson from `/opt/homelab/ros-zenoh/Dockerfile` (`ros:kilted-ros-base` pinned by digest + `ros-kilted-rmw-zenoh-cpp`, runs as `ubuntu`) | role `ros_zenoh_router`; also built and signed in CI as `ghcr.io/nikghodki/ros-zenoh` |
| `ros2-kilted` CLI on the Jetson | `/usr/local/bin/ros2-kilted` (runs `ros2` inside the router container) | role `ros_zenoh_router` |
| RoboStack env `ros2_kilted` | Pi `~/.local/share/mamba/envs/ros2_kilted` | one-time manual step |
| MS200 driver build (`oradar_lidar`) | Pi `~/ros2_ws` | one-time manual step |
| LiDAR node (`/scan`, `/tf_static` base_link → laser_frame at z 0.18 m) | Pi, user unit `ros-lidar.service` | role `ros_lidar` |
| Zenoh settings, session config, launch file | Pi `~/.config/homelab-ros/` | role `ros_lidar` |
| `ros2-kilted` CLI on the Pi | `~/.local/bin/ros2-kilted` | role `ros_lidar` |
| Uptime check | Gatus `Zenoh router (ROS 2)`, `tcp://192.168.86.211:7447` (runs on the Dell) | `playbooks/alerting.yml` |

## Versions

| | Jetson | Pi |
|---|---|---|
| ROS 2 | Kilted (`ros:kilted-ros-base`, Ubuntu 24.04 arm64) | Kilted, RoboStack `ros-kilted-ros-base 0.12.0` (Python 3.12) |
| rmw_zenoh | 0.6.8 (apt) | 0.6.9 |
| Zenoh | 1.8.0 | 1.9.0 |

Zenoh 1.8 and 1.9 interoperate. Keep both hosts on the same ROS distro.

## LiDAR settings (`roles/ros_lidar/defaults/main.yml`)

`/dev/ttyUSB0`, 230400 baud, motor speed 10, range 0.05–20 m, 0–360°, frame `laser_frame`, topic `scan`. The account
needs `dialout` (the role adds it).

## Why this layout

- One distro, Kilted: the newest with `rmw_zenoh` as Tier 1, available both as a `ros` arm64 image and in RoboStack.
- Jetson in a container: keeps hundreds of ROS packages off JetPack's Ubuntu.
- Pi in RoboStack: Debian trixie has no ROS packages; the restored Humble envs can't mix with newer distros.
- **Pi in Zenoh client mode**: in peer mode the Jetson never saw `/scan` (rmw_zenoh peers advertise `tcp/localhost:0`).
  `ZENOH_CONFIG_OVERRIDE='mode="client";connect/endpoints=["tcp/192.168.86.211:7447"]'` in `~/.config/homelab-ros/zenoh.env`.

## One-time setup on the Pi

```bash
export PATH=$HOME/.local/bin:$PATH        # micromamba 2.x
micromamba create -y -n ros2_kilted -c robostack-kilted -c conda-forge \
  ros-kilted-ros-base ros-kilted-rmw-zenoh-cpp=0.6.9 \
  compilers cmake pkg-config make ninja colcon-common-extensions
mkdir -p ~/ros2_ws/src && cp -a ~/ros2-test/oradar_ws/src/oradar_ms200 ~/ros2_ws/src/
cd ~/ros2_ws && micromamba run -n ros2_kilted colcon build --symlink-install --packages-select oradar_lidar \
  --cmake-args -DCMAKE_BUILD_TYPE=Release
```

About 10 minutes and 2.3 GB for the env, 1 minute for the build. Then from dgx-1:
`ansible-playbook playbooks/robot.yml --check --diff` and for real. The role fails clearly if the build is missing.

## Check

```bash
ros2-kilted topic list         # /parameter_events /rosout /scan /tf_static
ros2-kilted node list          # /MS200 /base_link_to_laser
ros2-kilted topic hz /scan     # ~10 Hz
```

Measured 2026-11-15 on the Jetson, 60 s: **10.065 Hz** average (min gap 0.000 s, max 0.455 s, std dev 0.051 s, 603
messages); the Pi's own CLI showed 10.056 Hz.

## Restart

```bash
sudo systemctl restart ros-zenoh-router          # Jetson
systemctl --user restart ros-lidar               # Pi
```

Both restart on failure. When the router restarts, the Pi's session reconnects by itself. When the router is down at
boot, the Pi node exits (client mode gives up at once) and systemd retries every 5 s. To rebuild the router image,
change `ros_zenoh_router_base_image` and bump `ros_zenoh_router_image_tag`.

## Known issues

- **RoboStack config mismatch:** rmw_zenoh 0.6.9 ships a session config with a `transport/shared_memory/.../messages`
  key its libzenohc 1.9.0 rejects (`Invalid configuration file` / `RCLBadAlloc`). The role writes
  `~/.config/homelab-ros/zenoh-session.json5` without the keys in `ros_lidar_session_drop_keys` and points
  `ZENOH_SESSION_CONFIG_URI` at it.
- **Jitter:** Wi-Fi makes arrivals bursty (0–0.5 s); the average is steady. Recheck before SLAM/Nav2.
- **LAN only, no auth:** the Pi connects to `tcp/192.168.86.211:7447`; there is no Zenoh auth or TLS, and the port is
  open on the LAN.
- `ros2-kilted` on the Jetson only works while the router runs; the image has only `ros-base` + rmw_zenoh.
- The Gatus TCP check proves the port is open, not that `/scan` flows (the governor's `SafetyGovernorLidarStale` does).
- runbooks/robot-ros.md still says the Gatus check runs on dgx-2; Gatus moved to the Dell (PR #55).
