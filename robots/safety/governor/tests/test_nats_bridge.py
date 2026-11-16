"""NatsBridge connect loop, with a stub `nats` module (the real client isn't installed for unit tests)."""
import asyncio
import json
import sys
import types

import pytest


@pytest.fixture
def bridge_mod(monkeypatch):
    stub = types.ModuleType("nats")
    monkeypatch.setitem(sys.modules, "nats", stub)
    monkeypatch.delitem(sys.modules, "safety_governor.nats_bridge", raising=False)
    import safety_governor.nats_bridge as mod

    return mod, stub


def test_missing_credentials_file_is_logged_and_retried(bridge_mod, tmp_path, monkeypatch):
    mod, stub = bridge_mod
    logs, connects = [], []
    creds = tmp_path / "creds.json"
    cfg = {"credentials_file": str(creds), "ca_file": None, "url": "tls://nats:4222",
           "estop_subject": "e", "reset_subject": "r"}

    class FakeConn:
        is_connected = True

        async def subscribe(self, subject, cb):
            pass

    async def connect(**kw):
        connects.append(kw)
        return FakeConn()

    stub.connect = connect
    real_sleep = asyncio.sleep

    async def fast_sleep(_seconds):
        # the credentials file appears while the bridge waits to retry (e.g. a deploy writes it late)
        creds.write_text(json.dumps({"user": "gov", "password": "pw"}))
        await real_sleep(0)

    monkeypatch.setattr(mod.asyncio, "sleep", fast_sleep)
    bridge = mod.NatsBridge(cfg, lambda s: None, lambda s: None, lambda: None,
                            lambda level, msg: logs.append((level, msg)))
    asyncio.run(bridge._main())
    assert any(level == "warning" and "FileNotFoundError" in msg for level, msg in logs), logs
    assert len(connects) == 1 and connects[0]["user"] == "gov"
    assert any("NATS connected" in msg for _, msg in logs)
