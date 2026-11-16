# 0014: NATS in k3s: three servers (both Sparks + the Jetson), JetStream R3, a VIP and the Sparks' Tailscale IPs

- Date: 2026-11-16
- Status: decided (prepared); the cutover is user-present and not applied yet ([runbooks/nats.md](../runbooks/nats.md#cutover))

## Context

NATS (D5) runs as one Docker container on dgx-1 (`bus-nats-1`, `hosts/stacks/bus`): NATS on `:4222` and MQTT on
`:8883`, both TLS, JetStream on (the MQTT gateway needs it), accounts `FLEET` and `SYS`, five users, no leafnodes or
cluster. It carries the robot's NATS e-stop and reset (`robot.pi.safety.*`, runbooks/robot-safety.md) and the
Hermes → picoclaw MQTT requests. dgx-1 failing takes the bus with it; plan phase 3 puts it in k3s as three servers.
Measured on 2026-11-16:

- **Clients** (repo and hosts, by file name and URL; `connz` on the server): the safety governor and the safety CLIs
  (Pi, dgx-1) on `tls://nats.nghodki.ai:4222`; picoclaw (Pi) and Hermes' MCP (Jetson) on `ssl://nats.nghodki.ai:8883`;
  Gatus (Dell) by IP `192.168.86.44`. Everything else uses the name, and the certificate is checked against it.
- **Paths**: the governor and Hermes reach dgx-1 over the LAN; picoclaw over Tailscale (the tailnet view of
  `nats.nghodki.ai` answers dgx-1's Tailscale IP and LAN IP). Tailscale grants 4222/8883 on dgx-1 to `tag:agent`,
  `tag:home`, `tag:robot`.
- **JetStream**: only the MQTT gateway's five streams (two sessions, no retained or in-flight messages); no streams or
  KV buckets of our own.
- **Nodes**: the Sparks have memory to spare for something this small; the Jetson (third etcd member, tainted) has
  ~2.3 GiB for pods. A NATS server with MQTT on uses ~13 MiB.

## Decision

- **Three servers, a StatefulSet in namespace `nats`**: one each on dgx-1, dgx-2 and the Jetson (required node
  affinity and anti-affinity; the Jetson's taint tolerated; requests 64 Mi, limit 256 Mi), `local-path` volumes, PDB
  `maxUnavailable: 1`, lame duck on stop. JetStream clustered, the MQTT gateway's streams **R3**
  (`mqtt.stream_replicas: 3`): any one server, the Jetson's Wi-Fi included, can go without losing the bus or MQTT
  sessions. The Jetson is the third peer because it is the third etcd member too; the same node set keeps quorum in
  the same failures as the cluster itself.
- **Same config, same users, same permissions** as the Docker server (`nats.conf` mirrors `nats.conf.j2`, checked
  identical at the time of writing). The password hashes come from `secrets/bus.enc.yaml` into a KSOPS Secret as NATS
  variables, so the permissions that keep the reset human-only stay readable in Git.
- **TLS**: clients get the existing `nats.crt` / `pki_nats_key` (SAN `nats.nghodki.ai`), so no client changes its CA or
  name. Routes use mutual TLS with a CA made only for them (its key discarded after signing): a route bypasses every
  user and permission, so no other certificate of the homelab CA may join.
- **LAN: a new kube-vip VIP, `192.168.86.12`** (LoadBalancer Service `nats-lan`, ports 4222/8883, no NodePorts),
  next to `.10`/`.11` and below the DHCP pool; nothing answered it (ping, arping). Its own address, not a port on
  the edge VIP: the bus mustn't depend on the front door's Services, and the VIP can move separately if that is ever
  needed (today one lease holds all service VIPs). Added to `tailscale_vip_guard`.
- **Tailnet: the Sparks' Tailscale IPs as `externalIPs`** (`nats-tailnet`), like the front door (decision 0007), not a
  subnet route for the VIP. picoclaw already uses the tailnet path; the Tailscale IPs never move and need no route
  approval. The tailnet view of `nats.nghodki.ai` answers the answering Spark's Tailscale IP plus the VIP (target
  `bus` in `edge-zone.py`); Tailscale gains grants for dgx-2:4222/8883. This Service goes in only with the Docker
  server stopped: on dgx-1 it takes the Tailscale IP's ports from Docker at once.
- **Clients move by DNS**: `nats.nghodki.ai` from `dgx-1` to `bus`. No client config changes except Gatus (by IP).
- **Prepared, inert until a user-present cutover.** The Application is kept in `cluster/apps/nats/` (not in
  `cluster/bootstrap/apps`), `names.txt` is unchanged, and the tailnet Service isn't in the kustomization. The cutover
  (runbooks/nats.md) needs the user present, the robot docked and the e-stop latched, starts the servers beside Docker
  first (verified on the VIP and each pod: routes, permissions, MQTT both ways, one server down), then moves the
  clients and stops Docker within minutes, so the bus is never split for long while the e-stop isn't latched.
- **fleet-mosquitto stays in Docker** (MQTT 5 for the Edge Connector; NATS's MQTT is 3.1.1).

## Alternatives considered

- **Helm chart (nats-io/k8s)**: more knobs (config reloader, box, exporter) than this needs, more images to pin and
  allow; a plain StatefulSet with one image is easier to review against the Docker config.
- **Two servers (Sparks only)**: JetStream needs a majority; two servers stop when either Spark does.
- **The Jetson as a client-free peer**: a Service selecting only the Sparks' pods would keep client traffic off the
  Jetson's Wi-Fi, but needs a label per pod that a StatefulSet doesn't give; the Pi and the Jetson are on Wi-Fi anyway.
  Revisit if the Jetson's pod causes trouble.
- **A subnet route for the VIP**: as in decision 0007, it adds Tailscale's subnet-router failover and `--accept-routes`
  on every Linux client.
- **Plaintext routes behind the NetworkPolicy**: the Jetson's routes cross the Wi-Fi; mutual TLS costs one Secret.
- **Migrating the MQTT streams**: nothing in them outlives a reconnect (two sessions, no retained messages).

## Consequences

- Losing dgx-1 no longer takes the bus (and the NATS e-stop) with it. Losing both Sparks does (no quorum).
- During the cutover the NATS e-stop is briefly unavailable or split; the e-stop is latched beforehand and the ROS
  e-stop keeps working.
- Two configs to keep identical until the Docker server is retired (a follow-up after the cutover).
- The monitoring endpoint is only reachable through `kubectl port-forward`; no scrape yet.
