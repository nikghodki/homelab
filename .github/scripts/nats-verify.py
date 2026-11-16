#!/usr/bin/env python3
"""Check a NATS deployment end to end without touching the robot (runbooks/nats.md).

Run on dgx-1 with the operator safety CLI's Python (it has nats-py):
  ~/.local/share/safety-cli/venv/bin/python .github/scripts/nats-verify.py [options] < creds.json

Credentials never go on a command line. --fleet-creds reads them on dgx-1: the operator's from
/etc/safety-operator/nats-operator.json (sudo -n cat) and the agent user's password (--agent-user, default picoclaw)
from secrets/bus.enc.yaml (sops). Without it, JSON on stdin: {"operator": {"user": ..., "password": ...},
"agent": {"user": "picoclaw", "password": ...}} (agent optional).
Checks, each one line PASS/FAIL (exit 1 on any FAIL):
  routes   for every pair of --server URLs: subscribe on one, publish on the other (the cluster routes)
  deny     the agent user may not publish robot.pi.safety.test.reset (the server refuses it, nothing arrives)
  mqtt     MQTT over TLS as the agent user (own client id, clean session): a NATS publish reaches the MQTT
           subscriber, and an MQTT publish (as Hermes' stop does) reaches a NATS subscriber
  status   the governor's robot.pi.safety.status arrives through this server (it is connected here); prints state
Only the test subjects robot.pi.safety.test.estop / .test.reset are published. The deployed governor listens on
robot.pi.safety.estop and .reset only, so nothing here can latch or clear the real e-stop. --expect-status makes a
missing status a FAIL (after the cutover); without it a missing status is only reported (before the cutover the
governor is still on the Docker server).
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
import pathlib
import secrets
import socket
import ssl
import struct
import subprocess
import sys
from urllib.parse import urlparse

import nats

TEST_ESTOP = "robot.pi.safety.test.estop"
TEST_RESET = "robot.pi.safety.test.reset"
STATUS = "robot.pi.safety.status"
failed = False


def report(ok: bool, check: str, detail: str) -> None:
    global failed
    failed |= not ok
    print(f"{'PASS' if ok else 'FAIL'} {check}: {detail}")


def tls_ctx(ca: str) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=ca)


async def connect(url: str, creds: dict, args, errors: list | None = None):
    async def error_cb(exc):
        if errors is not None:
            errors.append(str(exc))

    return await nats.connect(
        servers=[url], user=creds["user"], password=creds["password"], tls=tls_ctx(args.ca),
        tls_hostname=args.tls_name, name="nats-verify", connect_timeout=5, max_reconnect_attempts=0,
        allow_reconnect=False, error_cb=error_cb,
    )


async def check_routes(args, op: dict) -> None:
    urls = args.server
    pairs = list(itertools.permutations(urls, 2)) or [(urls[0], urls[0])]
    for sub_url, pub_url in pairs:
        nonce = secrets.token_hex(4)
        a = await connect(sub_url, op, args)
        b = a if sub_url == pub_url else await connect(pub_url, op, args)
        try:
            sub = await a.subscribe(TEST_ESTOP)
            await a.flush()
            await asyncio.sleep(0.5)  # interest propagates over the routes
            await b.publish(TEST_ESTOP, f"nats-verify {nonce}".encode())
            await b.flush()
            got = False
            try:
                while True:
                    msg = await sub.next_msg(timeout=3)
                    if msg.data.decode().endswith(nonce):
                        got = True
                        break
            except Exception:  # noqa: BLE001 - timeout
                pass
            report(got, "routes", f"publish on {pub_url} -> subscriber on {sub_url}")
        finally:
            for c in {id(a): a, id(b): b}.values():
                await c.drain()


async def check_deny(args, op: dict, agent: dict) -> None:
    url = args.server[0]
    errors: list = []
    watcher = await connect(url, op, args)
    ag = await connect(url, agent, args, errors)
    try:
        sub = await watcher.subscribe(TEST_RESET)
        await watcher.flush()
        await ag.publish(TEST_RESET, b"RESET")
        await ag.flush()
        await asyncio.sleep(1)
        arrived = False
        try:
            await sub.next_msg(timeout=1)
            arrived = True
        except Exception:  # noqa: BLE001 - timeout: nothing arrived, as it should
            pass
        refused = any("ermission" in e for e in errors)
        report(refused and not arrived, "deny",
               f"{agent['user']} publish {TEST_RESET}: refused={refused}, delivered={arrived}")
    finally:
        await ag.close()
        await watcher.drain()


def _mqtt_str(s: str) -> bytes:
    b = s.encode()
    return struct.pack("!H", len(b)) + b


def _mqtt_packet(ptype: int, body: bytes) -> bytes:
    n, rem = len(body), b""
    while True:
        byte, n = n % 128, n // 128
        rem += bytes([byte | (0x80 if n else 0)])
        if not n:
            return bytes([ptype]) + rem + body


def _mqtt_read(sock) -> tuple[int, bytes]:
    head = sock.recv(1)
    if not head:
        raise ConnectionError("MQTT connection closed")
    mult, length = 1, 0
    while True:
        b = sock.recv(1)[0]
        length += (b & 0x7F) * mult
        mult *= 128
        if not b & 0x80:
            break
    body = b""
    while len(body) < length:
        chunk = sock.recv(length - len(body))
        if not chunk:
            raise ConnectionError("MQTT connection closed")
        body += chunk
    return head[0] >> 4, body


async def check_mqtt(args, op: dict, agent: dict) -> None:
    host = urlparse(args.server[0]).hostname
    port = args.mqtt_port
    nonce = secrets.token_hex(4)
    client_id = f"nats-verify-{nonce}"  # never picoclaw-pi's id: that would take over its session
    raw = socket.create_connection((host, port), timeout=5)
    sock = tls_ctx(args.ca).wrap_socket(raw, server_hostname=args.tls_name)
    try:
        flags = 0x80 | 0x40 | 0x02  # user name, password, clean session
        body = _mqtt_str("MQTT") + bytes([4, flags]) + struct.pack("!H", 30) + _mqtt_str(client_id)
        body += _mqtt_str(agent["user"]) + _mqtt_str(agent["password"])
        sock.sendall(_mqtt_packet(0x10, body))
        ptype, ack = _mqtt_read(sock)
        if ptype != 2 or ack[1] != 0:
            report(False, "mqtt", f"CONNACK type {ptype} code {ack[1] if len(ack) > 1 else '?'}")
            return
        topic = TEST_ESTOP.replace(".", "/")
        sock.sendall(_mqtt_packet(0x82, struct.pack("!H", 1) + _mqtt_str(topic) + b"\x00"))
        ptype, ack = _mqtt_read(sock)
        if ptype != 9 or ack[-1] == 0x80:
            report(False, "mqtt", f"SUBACK type {ptype} refused")
            return
        nc = await connect(args.server[0], op, args)
        try:
            await asyncio.sleep(0.5)
            await nc.publish(TEST_ESTOP, f"nats-verify {nonce}".encode())
            await nc.flush()
        finally:
            await nc.drain()
        got = False
        sock.settimeout(3)
        try:
            while not got:
                ptype, body = _mqtt_read(sock)
                if ptype == 3:
                    tlen = struct.unpack("!H", body[:2])[0]
                    got = body[2 + tlen:].decode(errors="replace").endswith(nonce)
        except (socket.timeout, ConnectionError):
            pass
        report(got, "mqtt", f"{agent['user']} via {host}:{port}, NATS {TEST_ESTOP} -> MQTT {topic}")
        # The other way, as Hermes' `stop` does: an MQTT publish arrives on the NATS subject.
        nonce2 = secrets.token_hex(4)
        nc = await connect(args.server[0], op, args)
        try:
            sub = await nc.subscribe(TEST_ESTOP)
            await nc.flush()
            await asyncio.sleep(0.5)
            sock.sendall(_mqtt_packet(0x30, _mqtt_str(topic) + f"nats-verify {nonce2}".encode()))  # QoS 0
            got = False
            try:
                while not got:
                    msg = await sub.next_msg(timeout=3)
                    got = msg.data.decode(errors="replace").endswith(nonce2)
            except Exception:  # noqa: BLE001 - timeout
                pass
        finally:
            await nc.drain()
        report(got, "mqtt", f"{agent['user']} MQTT {topic} -> NATS {TEST_ESTOP}")
        sock.sendall(bytes([0xE0, 0]))  # DISCONNECT
    finally:
        sock.close()


async def check_status(args, op: dict) -> None:
    nc = await connect(args.server[0], op, args)
    try:
        sub = await nc.subscribe(STATUS)
        try:
            msg = await sub.next_msg(timeout=args.status_timeout)
        except Exception:  # noqa: BLE001 - timeout
            msg = None
        if msg is None:
            text = f"no {STATUS} within {args.status_timeout} s via {args.server[0]}"
            if args.expect_status:
                report(False, "status", text)
            else:
                print(f"INFO status: {text} (the governor is connected elsewhere)")
            return
        st = json.loads(msg.data)
        report(True, "status", f"state={st.get('state')} reason={st.get('reason')} "
                               f"estop_latched={st.get('estop', {}).get('latched')} sink={st.get('sink')}")
    finally:
        await nc.drain()


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", action="append", required=True, help="tls://host:port, repeat for each server")
    p.add_argument("--tls-name", default="nats.nghodki.ai", help="name to verify the server certificate against")
    p.add_argument("--ca", default="/usr/local/share/ca-certificates/homelab-ca.crt")
    p.add_argument("--mqtt-port", type=int, default=8883)
    p.add_argument("--checks", default="routes,deny,mqtt,status")
    p.add_argument("--fleet-creds", action="store_true", help="read the credentials on dgx-1 (sudo, sops)")
    p.add_argument("--agent-user", default="picoclaw", choices=["picoclaw", "hermes"])
    p.add_argument("--expect-status", action="store_true")
    p.add_argument("--status-timeout", type=float, default=5)
    args = p.parse_args()
    if args.fleet_creds:
        run = lambda cmd: subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        repo = pathlib.Path(__file__).resolve().parents[2]
        creds = {
            "operator": json.loads(run(["sudo", "-n", "cat", "/etc/safety-operator/nats-operator.json"])),
            "agent": {"user": args.agent_user, "password": run(
                ["sops", "-d", "--extract", f'["nats_{args.agent_user}_password"]', str(repo / "secrets/bus.enc.yaml")]
            ).strip()},
        }
    else:
        creds = json.loads(sys.stdin.read())
    op, agent = creds["operator"], creds.get("agent")
    checks = args.checks.split(",")
    if "routes" in checks:
        await check_routes(args, op)
    for name, fn in (("deny", check_deny), ("mqtt", check_mqtt)):
        if name in checks:
            if agent:
                await fn(args, op, agent)
            else:
                print(f"SKIP {name}: no agent credentials")
    if "status" in checks:
        await check_status(args, op)
    print("RESULT: " + ("FAILED" if failed else "OK"))
    return 1 if failed else 0


if __name__ == "__main__":
    logging.getLogger("asyncio").setLevel(logging.ERROR)  # "returning true from eof_received()" noise with TLS
    sys.exit(asyncio.run(main()))
