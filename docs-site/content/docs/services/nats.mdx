---
title: "NATS"
description: "The fleet message bus on dgx-1: NATS with JetStream and MQTT over TLS, its accounts and permissions, and the e-stop subjects."
---

NATS (D5) is the general event bus. MQTT clients (picoclaw, later Home Assistant) connect to its MQTT listener with
their own accounts. Request/reply between agents is planned to go through LiteLLM A2A instead (D20).

| | |
|---|---|
| Version | NATS 2.15.3 (`nats:2.15.3-alpine`, digest-pinned), server name `homelab-bus-1`, one node |
| Host | dgx-1, stack `bus` (`hosts/stacks/bus`, `playbooks/bus.yml`), `/opt/homelab/bus` |
| Ports | 4222 NATS (TLS), 8883 MQTT (TLS), 127.0.0.1:8222 monitoring |
| Name | `nats.nghodki.ai` (dnsmasq → dgx-1) |
| TLS | `nats.crt` from the internal homelab CA; key `pki_nats_key` in `secrets/pki.enc.yaml`. Clients need `homelab-ca.crt` |
| JetStream | `/data` (volume `bus_nats-data`), max memory store 256 MB, max file store 20 GB |
| Limits | `max_payload: 1MB` |
| Secrets | `secrets/bus.enc.yaml`: bcrypt `nats_*_password_hash` rendered into `nats.conf`; plaintext passwords for clients |
| Health | Gatus `NATS (TLS)` (tcp 4222), `NATS MQTT (picoclaw)` (tcp 8883) |
| k3s target | `bus`, 3 replicas (dgx-1, dgx-2, a small one on the Jetson) |

## Accounts and permissions (`nats.conf.j2`)

Account `FLEET` (JetStream on) and `SYS` (system account, user `sys`). Deny wins over allow, for MQTT publishes too.

| User | Publish | Subscribe | Used by |
|---|---|---|---|
| `admin` | everything | everything | you |
| `picoclaw` | `/.picoclaw.>`, `robot.pi.>`, `$MQTT.>`; **deny** `robot.pi.safety.reset`, `robot.pi.safety.test.reset` | `/.picoclaw.>`, `robot.pi.cmd.>`, `robot.pi.safety.>`, `$MQTT.>`, `_INBOX.>` | picoclaw over MQTT (topic `/picoclaw/...` is subject `/.picoclaw...`); the safety governor; `safety-estop` on the Pi |
| `hermes` | `/.picoclaw.>`, `robot.>`, `agents.hermes.>`, `home.>`, `$MQTT.>`, `_INBOX.>`; **deny** the reset subjects | same subjects (no deny) | Hermes's picoclaw MCP (`~hermes-nikhil/.picoclaw-nats-credentials`, 0600) |
| `operator` | `robot.pi.safety.reset`, `robot.pi.safety.estop` and their `.test.` versions | `robot.pi.safety.>` | the human: `safety-reset` / `safety-estop` on dgx-1 and the Pi |
| `sys` | (system) | (system) | monitoring |

Anonymous connections are refused (P1.5 acceptance).

## Subjects in use

| Subject | Who publishes | Who listens |
|---|---|---|
| `/.picoclaw.>` (MQTT `/picoclaw/...`) | Hermes, picoclaw | picoclaw, Hermes |
| `robot.pi.safety.estop` | anyone with `robot.pi.>` (any payload latches) | safety governor |
| `robot.pi.safety.reset` | `operator` only, payload `RESET` | safety governor |
| `robot.pi.safety.status` | safety governor (JSON, 1 Hz + on change) | `safety-estop status` |
| `robot.pi.cmd.heartbeat` | the commanding side | safety governor |
| `robot.pi.safety.test.*` | the integration test | the test governor |

The architecture's other subjects (`home.presence.*`, `models.<node>.status`, `jobs.*`, `security.*`, `fleet.*`) are
planned, not in use.

## Change

Add a user: password and bcrypt hash (`$2a$`, cost 10, python `bcrypt` in the Ansible venv) into `secrets/bus.enc.yaml`
with `sops set --value-stdin`, add the user to `nats.conf.j2` and the hash variable to `playbooks/bus.yml`, then
`ansible-playbook playbooks/bus.yml --check --diff` and for real. NATS restarts for a moment; clients reconnect.

`playbooks/bus.yml` also installs the operator safety CLI on dgx-1 (play "Operator safety CLI").

## Gotchas

- NATS MQTT is MQTT 3.1.1 only. That's why DefenseClaw Fleet (MQTT 5) has its own Mosquitto broker.
- 4222 and 8883 bind all interfaces on dgx-1. Tailscale grants them to `tag:agent`, `tag:home`, `tag:robot` only.
- If NATS is down, the governor can't receive a NATS e-stop or reset. Use the ROS e-stop.
