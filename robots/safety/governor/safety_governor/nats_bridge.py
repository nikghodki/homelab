"""NATS side of the governor: e-stop, reset and heartbeat in, status out. Runs its own asyncio
loop in a thread; callbacks are called from that thread."""

from __future__ import annotations

import asyncio
import json
import ssl
import threading

import nats

RESET_WORD = b"RESET"


class NatsBridge:
    def __init__(self, cfg: dict, on_estop, on_reset, on_heartbeat, log) -> None:
        self._cfg = cfg
        self._on_estop = on_estop
        self._on_reset = on_reset
        self._on_heartbeat = on_heartbeat
        self._log = log
        self._loop = asyncio.new_event_loop()
        self._nc = None
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="nats", daemon=True)

    @property
    def connected(self) -> bool:
        nc = self._nc
        return bool(nc and nc.is_connected)

    def start(self) -> None:
        self._thread.start()

    def publish(self, subject: str, payload: bytes) -> None:
        if self.connected:
            asyncio.run_coroutine_threadsafe(self._nc.publish(subject, payload), self._loop)

    def close(self) -> None:
        self._stop = True

        async def shutdown():
            if self._nc is not None and not self._nc.is_closed:
                await self._nc.drain()
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task():
                    task.cancel()

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), self._loop).result(timeout=3)
        except Exception:  # noqa: BLE001 - shutting down anyway
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._main())
        self._loop.run_forever()

    async def _main(self) -> None:
        cfg = self._cfg
        with open(cfg["credentials_file"], encoding="utf-8") as fh:
            creds = json.load(fh)
        tls = ssl.create_default_context(cafile=cfg["ca_file"])

        async def error_cb(exc):
            self._log("warning", f"NATS error: {exc}")

        async def disconnected_cb():
            self._log("warning", "NATS disconnected (e-stop over NATS unavailable until it reconnects)")

        async def reconnected_cb():
            self._log("info", "NATS reconnected")

        while not self._stop:
            try:
                self._nc = await nats.connect(
                    servers=[cfg["url"]],
                    user=creds["user"],
                    password=creds["password"],
                    tls=tls,
                    name="safety-governor",
                    connect_timeout=5,
                    allow_reconnect=True,
                    max_reconnect_attempts=-1,
                    reconnect_time_wait=2,
                    error_cb=error_cb,
                    disconnected_cb=disconnected_cb,
                    reconnected_cb=reconnected_cb,
                )
                break
            except Exception as exc:  # noqa: BLE001 - keep retrying; the robot doesn't need NATS to stay safe
                self._log("warning", f"NATS connect failed ({type(exc).__name__}: {exc}); retrying in 5 s")
                await asyncio.sleep(5)
        if self._stop:
            return

        async def estop(msg):
            self._on_estop("nats")

        async def reset(msg):
            if msg.data.strip().upper() == RESET_WORD:
                self._on_reset("nats")
            else:
                self._log("warning", f"ignored reset on {msg.subject}: payload must be RESET")

        async def heartbeat(msg):
            self._on_heartbeat()

        await self._nc.subscribe(cfg["estop_subject"], cb=estop)
        await self._nc.subscribe(cfg["reset_subject"], cb=reset)
        if cfg.get("heartbeat_subject"):
            await self._nc.subscribe(cfg["heartbeat_subject"], cb=heartbeat)
        self._log("info", f"NATS connected to {cfg['url']}; e-stop on {cfg['estop_subject']}")
