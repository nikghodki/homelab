# Robot ROS 2 (rmw_zenoh) and the Pi's LiDAR

Plan P5.1: ROS 2 on the Jetson and the Pi with `rmw_zenoh` as the middleware, a Zenoh router on the
Jetson, and the Pi's Oradar MS200 LiDAR on `/scan`. Playbook: `hosts/playbooks/robot.yml`.
Nothing here moves the robot: the only node is the LiDAR driver (plus a static transform).

| Piece | Where | Managed by |
|---|---|---|
| Zenoh router `rmw_zenohd`, `tcp/[::]:7447` | Jetson, system unit `ros-zenoh-router.service` (Docker container `ros-zenoh-router`, host network) | role `ros_zenoh_router` |
| Router image `homelab/ros-zenoh:kilted-1` | Jetson, built from `/opt/homelab/ros-zenoh/Dockerfile` | role `ros_zenoh_router` |
| ROS 2 CLI on the Jetson: `ros2-kilted` | `/usr/local/bin/ros2-kilted` (runs `ros2` inside the router container) | role `ros_zenoh_router` |
| RoboStack env `ros2_kilted` | Pi `~/.local/share/mamba/envs/ros2_kilted` | one-time manual step (below) |
| MS200 driver build (`oradar_lidar`) | Pi `~/ros2_ws` | one-time manual step (below) |
| LiDAR node, `/scan` + `/tf_static` | Pi, user unit `ros-lidar.service` (linger on) | role `ros_lidar` |
| Zenoh settings, session config, launch file | Pi `~/.config/homelab-ros/` | role `ros_lidar` |
| ROS 2 CLI on the Pi: `ros2-kilted` | Pi `~/.local/bin/ros2-kilted` | role `ros_lidar` |
| Uptime check "Zenoh router (ROS 2)", `tcp://192.168.86.211:7447` | Gatus (dgx-2), group `robot` | `playbooks/observe.yml` |

## Versions (2026-11-15)

| | Jetson | Pi |
|---|---|---|
| ROS 2 | Kilted, `ros:kilted-ros-base@sha256:e03695c2…` (Ubuntu 24.04, arm64) | Kilted, RoboStack `ros-kilted-ros-base 0.12.0` (Python 3.12) |
| rmw_zenoh | `ros-kilted-rmw-zenoh-cpp 0.6.8` (apt, in the image) | `ros-kilted-rmw-zenoh-cpp 0.6.9` |
| Zenoh | 1.8.0 (`zenoh_cpp_vendor`) | 1.9.0 (`libzenohc`) |

Zenoh 1.8 and 1.9 talk to each other fine. Keep both on the same ROS distro.

## Why this layout

- **One distro, Kilted**: the newest release with `rmw_zenoh` as a Tier 1 middleware, and both the
  `ros` Docker image (arm64) and RoboStack (`linux-aarch64`) have it with `rmw_zenoh_cpp`.
- **Jetson in a container**: JetPack is Ubuntu 24.04 with NVIDIA's packages; ROS from apt would mix
  hundreds of packages into the host. The container is pinned by digest, built by Ansible, and uses
  the host network, so the router listens on the Jetson's LAN address. (The old JetPack 6 install had
  Humble from apt; it was wiped by the JetPack 7 reflash.)
- **Pi in RoboStack**: Debian trixie has no ROS packages. The restored backup had RoboStack envs
  (`ros2_nav`, `ros2_test`), but they are **Humble**: older than Jazzy, and ROS 2 doesn't support
  mixing distros between hosts. A new `ros2_kilted` env sits next to them. The old envs and
  `~/ros2-test/oradar_ws` are untouched.
- **Pi in Zenoh client mode**: see Known issues.

## One-time setup on the Pi

The env takes about 10 minutes and 2.3 GB; the driver build about 1 minute.

```bash
export PATH=$HOME/.local/bin:$PATH        # micromamba 2.x
micromamba create -y -n ros2_kilted -c robostack-kilted -c conda-forge \
  ros-kilted-ros-base ros-kilted-rmw-zenoh-cpp=0.6.9 \
  compilers cmake pkg-config make ninja colcon-common-extensions

# The MS200 driver (Oradar's ROS 1/2 package "oradar_lidar"), from the restored workspace
mkdir -p ~/ros2_ws/src
cp -a ~/ros2-test/oradar_ws/src/oradar_ms200 ~/ros2_ws/src/
cd ~/ros2_ws
micromamba run -n ros2_kilted colcon build --symlink-install --packages-select oradar_lidar \
  --cmake-args -DCMAKE_BUILD_TYPE=Release
```

If the restored copy is ever gone, use Oradar's MS200 ROS driver from the vendor (the restored copy
is also in the Pi's restic backup, `~/ros2-test/oradar_ws/src`). Then, from dgx-1: `ansible-playbook playbooks/robot.yml --check --diff`
and without `--check`. The role fails with a clear message if the driver build is missing.

The account needs `dialout` for `/dev/ttyUSB0` (the role makes sure of it).

## Check `/scan`

On the Jetson:

```bash
ros2-kilted topic list            # /parameter_events /rosout /scan /tf_static
ros2-kilted node list             # /MS200 /base_link_to_laser
ros2-kilted topic hz /scan        # ~10 Hz
ros2-kilted topic echo --once /scan --field ranges
```

Measured on 2026-11-15, Jetson, 60 s window: **average rate 10.065 Hz** (min 0.000 s, max 0.455 s,
std dev 0.051 s, 603 messages). A parallel run of the Pi's own CLI showed the same (10.056 Hz). Before the role was in
place, a 15 s run showed 10.03 Hz with min 0.083 s / max 0.114 s.

On the Pi: `ros2-kilted topic hz /scan` (same thing; it also goes through the Jetson router).

## Restart

```bash
# Jetson
sudo systemctl restart ros-zenoh-router
journalctl -u ros-zenoh-router -f

# Pi
systemctl --user restart ros-lidar
journalctl --user-unit ros-lidar -f
```

Both units restart on failure (`Restart=always`). When the router restarts, the Pi's session
reconnects by itself (tested: no `ros-lidar` restart needed). When the router is down at boot, the
Pi node exits (client mode gives up at once) and systemd retries every 5 s until the router is back.

To rebuild the router image (new base digest or rmw_zenoh), change `ros_zenoh_router_base_image`
and bump `ros_zenoh_router_image_tag` in the role defaults, then run the playbook.

## Known issues

- **Peer mode doesn't work across hosts here.** With the default `mode: "peer"` and only
  `connect/endpoints` set, the Pi connected to the router but the Jetson never saw `/scan`: rmw_zenoh
  peers listen on `tcp/localhost:0`, so the other side's peer can't connect to the advertised
  locators, and the router didn't broker between them. The Pi therefore uses `mode: "client"`
  (`ZENOH_CONFIG_OVERRIDE` in `~/.config/homelab-ros/zenoh.env`): all traffic goes through the router.
  For many nodes on the Pi, a local router on the Pi connected to the Jetson's is the better shape.
- **RoboStack config mismatch.** RoboStack's `rmw_zenoh_cpp 0.6.9` ships a
  `DEFAULT_RMW_ZENOH_SESSION_CONFIG.json5` with a `transport/shared_memory/.../messages` key that its
  `libzenohc 1.9.0` doesn't know, so every node aborts with `Invalid configuration file` /
  `RCLBadAlloc`. The role writes `~/.config/homelab-ros/zenoh-session.json5` = the env's file without
  the keys in `ros_lidar_session_drop_keys`, and points `ZENOH_SESSION_CONFIG_URI` at it. If a later
  RoboStack build fixes this, the filter becomes a no-op.
- **Jitter.** The Pi is on Wi-Fi. Inter-arrival times range 0–0.5 s (bursts), the average is steady
  at 10 Hz. Fine for monitoring; check again before SLAM/Nav2 (P5.3).
- **Driver warnings.** The Oradar SDK has a `-Wreturn-type` warning in `uart_data_find_init_info`;
  the return value isn't used and the node runs fine.
- **LAN only.** The Pi connects to `tcp/192.168.86.211:7447`. Over Tailscale later: change
  `ros_lidar_zenoh_router`. There is no Zenoh auth/TLS yet; the router port is open on the LAN.
- `ros2-kilted` on the Jetson runs inside the router container, so it's only there while the router
  runs. The image has only `ros-base` + rmw_zenoh (no rviz, no Nav2; those come in P5.3).
- The Gatus TCP check only proves the port accepts connections, not that `/scan` flows.
