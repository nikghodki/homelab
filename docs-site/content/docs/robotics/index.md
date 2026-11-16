---
title: Robotics and simulation
description: The robot (an ESP32 car with a Pi), ROS 2 over Zenoh, the safety governor, and simulation jobs on dgx-2.
---

The robot is an ESP32 car with its own HTTP API, plus a Raspberry Pi 4 with an Oradar MS200 LiDAR. The Jetson runs the
Zenoh router (and later SLAM and Nav2). dgx-2 runs simulators for training policies.

| Loop | Where | Today |
|---|---|---|
| Under 10 ms: motors, LiDAR driver, **safety governor** | Pi | LiDAR driver and governor (mock sink) live |
| 50–200 ms: reflexes | Pi / car firmware | the car's firmware avoids obstacles on forward `/drive` with `avoid: true` and stops after 500 ms without `/velocity` |
| 0.1–1 s: SLAM, Nav2 | Jetson | not started (P5.3) |
| 1–10 s: task planning | DGX (`smart`) | via Hermes later |
| hours: training | dgx-2 | Isaac Lab and MuJoCo smoke runs done |

| Page | |
|---|---|
| [ROS 2 and Zenoh](ros-zenoh.md) | Kilted, rmw_zenoh, the router on the Jetson, `/scan` from the Pi |
| [Safety governor](safety-governor.md) | rules, NATS subjects, the human-only reset, the mock sink, the on-blocks test |
| [Simulation](simulation.md) | Isaac Lab 3.0 and MuJoCo Playground on dgx-2, measured numbers, memory caps, MLflow logging |

Plan status: P5.1 ✅, P5.2 built (the final on-blocks test needs you), P5.3–P5.7 not started; P6.2 and P6.4 ✅, P6.5 ✅
(MLflow), P6.3 (Isaac Sim) prepared, P6.1 and P6.6–P6.12 not started.

`robots/` in the repo holds `safety/` (limits and the governor) and `sim/` (images and `measure.sh`). The other
folders in `robots/README.md` (`models/`, `tasks/`, `policies/`, `maps/`) don't exist yet.
