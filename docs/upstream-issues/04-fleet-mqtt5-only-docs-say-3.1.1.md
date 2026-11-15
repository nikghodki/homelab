# Fleet gateway's MQTT client is MQTT 5 only, but the docs say MQTT 3.1.1 and "any standards-compliant broker works"

Target: github.com/cisco-ai-defense/defenseclaw

## Upstream check (2026-11-15)

- Issues and PRs searched: `MQTT 5`, `MQTT 3.1.1`, `paho`, `NATS`. Nothing reports it. PR #1343 edits
  `paho_client.go` (latency) but not the protocol version.
- `main` still uses `paho.golang` `autopaho`. Status: **not reported.**

## Version

DefenseClaw 1.0.9 OSS gateway with `fleet.enabled`. `go.mod`: `github.com/eclipse/paho.golang v0.23.0`.

## Environment

The gateway on Ubuntu arm64 (DGX Spark). Broker: NATS server with MQTT enabled (TLS), which supports MQTT 3.1.1 only.

## Steps to reproduce

1. Point `fleet` MQTT at a broker that speaks only MQTT 3.1.1, for example NATS with its MQTT listener, or AWS IoT /
   RabbitMQ setups without MQTT 5.
2. Start the gateway.

## Expected

The gateway connects, as the docs suggest. Or the docs say that the gateway needs an MQTT 5 broker.

## Actual

The broker refuses the CONNECT (NATS: `unacceptable protocol version of 5`). The gateway keeps reconnecting and never
subscribes to heartbeat, verdict or register topics.

## Evidence

- `internal/fleet/mqtt/paho_client.go:36-37,148` uses `github.com/eclipse/paho.golang/autopaho`, which implements
  MQTT v5 only.
- The C device uses 3.1.1: `edge-connector/src/comms/mqtt_client.c:613`, `opts.MQTTVersion = 4; /* MQTT 3.1.1 */`.
- Docs:
  - `edge-connector/README.md:3` says verdicts go "over MQTT 3.1.1".
  - `docs-site/content/docs/edge-connector/install.mdx:389` says "The Edge Connector uses MQTT 3.1.1 ... Any
    standards-compliant broker works".
  - `architecture.mdx:86` and `index.mdx:43` also say 3.1.1.

## Suggested fix

Either:

1. Document it: the device speaks 3.1.1 and the gateway speaks 5, so the broker must support both (Mosquitto, EMQX and
   HiveMQ do; NATS doesn't). Or,
2. Add a `fleet.mqtt.protocol_version: 4|5` option, using a 3.1.1-capable client (such as
   `eclipse/paho.mqtt.golang`) when 4 is set.

## Workaround we used

We run a separate Mosquitto 2.1.2 broker just for Fleet (TLS, password file, per-device exact-topic ACLs). It accepts
the gateway's MQTT 5 and the device's 3.1.1. The rest of the home lab stays on NATS.
