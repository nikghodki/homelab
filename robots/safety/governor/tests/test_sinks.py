"""Sink selection and the mock/HTTP sinks. Standard library + pytest only (no network)."""

import json
import threading

import pytest

from safety_governor.core import ZERO, Velocity
from safety_governor.sinks import HttpVelocitySink, MockSink, make_sink


def test_default_is_mock():
    sink, note = make_sink({})
    assert isinstance(sink, MockSink) and not sink.is_real and note == ""


@pytest.mark.parametrize("enabled", [False, None, "true", 1])
@pytest.mark.parametrize("kind", ["http_velocity", "ros_cmd_vel"])
def test_real_sink_needs_explicit_true(kind, enabled):
    cfg = {"kind": kind, "http_url": "http://192.0.2.1"}
    if enabled is not None:
        cfg["real_sink_enabled"] = enabled
    sink, note = make_sink(cfg, ros_factory=lambda: pytest.fail("must not build the real sink"))
    assert isinstance(sink, MockSink) and "real_sink_enabled" in note


def test_unknown_sink_rejected():
    with pytest.raises(ValueError):
        make_sink({"kind": "serial"})


def test_ros_sink_built_only_when_enabled():
    marker = object()
    sink, note = make_sink({"kind": "ros_cmd_vel", "real_sink_enabled": True}, ros_factory=lambda: marker)
    assert sink is marker and note == ""


def test_http_sink_needs_url():
    with pytest.raises(ValueError):
        make_sink({"kind": "http_velocity", "real_sink_enabled": True, "http_url": ""})


def test_mock_records_and_writes_jsonl(tmp_path):
    path = tmp_path / "sink.jsonl"
    sink = MockSink(str(path), clock=lambda: 12.5)
    sink.send(Velocity(0.1, 0.0, -0.2))
    sink.send(ZERO)
    sink.close()
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert lines == [{"t": 12.5, "vx": 0.1, "vy": 0.0, "wz": -0.2}, {"t": 12.5, "vx": 0.0, "vy": 0.0, "wz": 0.0}]
    assert len(sink.records) == 2


def test_http_sink_sends_latest_payload_and_survives_errors():
    sent = []
    errors = []
    done = threading.Event()

    def post(endpoint, payload, timeout):
        sent.append((endpoint, payload))
        if len(sent) == 1:
            raise OSError("car unreachable")
        done.set()

    sink = HttpVelocitySink("http://192.0.2.1/", post=post, on_error=errors.append)
    sink.send(Velocity(0.1, 0.0, 0.3))
    for _ in range(100):
        if errors:
            break
        threading.Event().wait(0.01)
    sink.send(ZERO)
    assert done.wait(2)
    sink.close()
    assert sent[0] == ("http://192.0.2.1/velocity", {"linear": 0.1, "angular": 0.3})
    assert sent[-1] == ("http://192.0.2.1/velocity", {"linear": 0.0, "angular": 0.0})
    assert len(errors) == 1
