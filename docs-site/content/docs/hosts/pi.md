---
title: "Raspberry Pi"
description: "The robot body: MS200 LiDAR driver, safety governor, picoclaw, DefenseClaw Edge Connector. Managed by Ansible only, not in k3s."
---

The Pi is the robot's body computer. Everything that keeps the robot safe runs here and keeps working when the
network is gone. It is not a k3s node.

## Hardware and OS

| | |
|---|---|
| Hostname | `nikghodki-raspberry` |
| Hardware | Raspberry Pi 4, 4 cores, 3.7 GiB, 1 TB SD card (4% used; replaced the 75%-full 32 GB card, P0.2) |
| Sensors | Oradar MS200 LiDAR on `/dev/ttyUSB0` (230400 baud), IMX219 camera (not used: vision is off) |
| OS | Debian 13 trixie (Raspberry Pi OS 64-bit), fresh install restored from backup (P0.2) |
| User | `nikghodki-raspberry-1` (passwordless sudo) |
| LAN | `wlan0` 192.168.86.39 (Wi-Fi). `eth0` down |
| Tailscale | 100.64.25.22, `nikghodki-raspberry`, `tag:robot` (same node as before the card swap) |

The robot itself is an ESP32 car with its own HTTP API (`firmware/roboclaw_firmware.ino` in the roboclaw project).
`roboclaw.local` does not resolve on the LAN; dnsmasq has `esp32.nghodki.ai` → 192.168.86.50 (unverified that this is
the car today).

## What runs here

| Unit | Kind | What | Listens |
|---|---|---|---|
| `edge-connector.service` | system, user `defenseclaw` | DefenseClaw Edge Connector 1.0.9 (built on the Pi), device 1/1/1 | — (MQTT out to dgx-1:8884) |
| `otelcol-contrib`, `fleet-metrics`, `tailscaled`, `ssh` | system | standard | 9109 |
| `picoclaw` | system, user `picoclaw` (uid 995) | picoclaw agent (since PR #73; home `/var/lib/picoclaw`), with the in-process DefenseClaw hook and its MCP server `picoclaw-hardware` (Node), motion via the bridge ([picoclaw](../agents/picoclaw.md)). The old user unit `picoclaw-gateway` is disabled | 127.0.0.1:18790 (unverified which process) |
| `robot-motion-bridge` | system, as the login user, group `robot-motion` | the governor's motion bridge; socket `/run/robot-motion/motion.sock` | — |
| `ros-lidar` | user (linger) | MS200 driver → `/scan` and `/tf_static` over Zenoh (client mode) | — |
| `safety-governor` | user | the safety governor, mock sink | metrics 127.0.0.1:9113 |
| `dclaw-tunnel` | user | Old SSH tunnel `-L 18970` to the Jetson's DefenseClaw gateway. Still enabled; the plan said to retire it (P1.12). See [discrepancies](../decisions/discrepancies.md) | — |

Timers: `cisco-aibom` (~04:20), `lynis-audit`, `homelab-backup`. No Docker.

ROS lives in a RoboStack env, `~/.local/share/mamba/envs/ros2_kilted` (micromamba 2.x in `~/.local/bin`). The MS200
driver is built in `~/ros2_ws`. The old Humble envs (`ros2_nav`, `ros2_test`) are still there, untouched.

## Operate

```bash
ssh -p 2248 nikghodki-raspberry-1@localhost       # from the admin laptop
systemctl --user status ros-lidar safety-governor
systemctl status picoclaw robot-motion-bridge
safety-estop status                                # governor state over NATS
journalctl -t safety-governor -f
sudo journalctl -u edge-connector -f
```

Changes to the robot (limits, governor code) are applied only while the robot is docked (`robots/README.md`).

## Gotchas

- Wi-Fi only. Bursty `/scan` arrival (0–0.5 s gaps), steady 10 Hz average.
- picoclaw runs as its own user without sudo, and the login home is 0750; the login user still has passwordless sudo.
- `pi.nghodki.ai` in dnsmasq still points at the old address 192.168.86.34 (see [discrepancies](../decisions/discrepancies.md)).
