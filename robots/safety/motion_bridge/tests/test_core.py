import json
import math

import pytest

from motion_bridge.core import (
    DEFAULTS,
    Plan,
    RequestError,
    load_config,
    parse_request,
    plan,
    precheck,
    summarize,
)

CFG = load_config({})


def test_defaults_are_valid_and_between_caps_and_ceiling():
    assert CFG == DEFAULTS
    # speed 255 is above the governor's caps (it clamps) and below its ceiling (it would reject)
    assert 0.2 < CFG["full_speed_linear"] < CFG["ceiling_linear"]
    assert 1.0 < CFG["full_speed_angular"] < CFG["ceiling_angular"]


@pytest.mark.parametrize("bad", [
    {"full_speed_linear": 0.5}, {"full_speed_linear": 0.0}, {"full_speed_angular": 3.0}, {"turn_rate": 2.5},
    {"default_duration_ms": 20000}, {"cmd_rate_hz": 2}, {"surprise": 1}, {"socket_mode": 0o777}, {"socket_mode": "660"},
])
def test_config_refuses_bad_values(bad):
    with pytest.raises(ValueError):
        load_config(bad)


def test_drive_forward_scales_speed():
    p = plan({"op": "drive", "direction": "forward", "speed": 255, "duration_ms": 1500}, CFG)
    assert p == Plan(0.4, 0.0, 1.5)
    p = plan({"op": "drive", "direction": "backward", "speed": 51}, CFG)
    assert p.vx == pytest.approx(-0.08) and p.wz == 0.0 and p.duration_s == 1.0  # default duration


def test_drive_spin_and_default_speed():
    p = plan({"op": "drive", "direction": "spin_right", "duration_ms": 500}, CFG)
    assert p.vx == 0.0 and p.wz == pytest.approx(-180 / 255 * 2.0)


@pytest.mark.parametrize("req", [
    {"op": "drive", "direction": "strafe_left"},
    {"op": "drive", "direction": "up"},
    {"op": "drive", "direction": "forward", "speed": 300},
    {"op": "drive", "direction": "forward", "speed": True},
    {"op": "drive", "direction": "forward", "duration_ms": 0},
    {"op": "drive", "direction": "forward", "duration_ms": 10001},
    {"op": "turn", "direction": "forward", "degrees": 90},
    {"op": "turn", "direction": "spin_left", "degrees": 0},
    {"op": "move", "vx": float("nan")},
    {"op": "move", "vx": "fast"},
    {"op": "status"},
])
def test_refused_requests(req):
    with pytest.raises(RequestError):
        plan(req, CFG)


def test_turn_by_degrees():
    p = plan({"op": "turn", "direction": "spin_left", "degrees": 90}, CFG)
    assert p.vx == 0.0 and p.wz == CFG["turn_rate"]
    assert p.duration_s == pytest.approx(math.pi / 2 / CFG["turn_rate"])
    assert plan({"op": "turn", "direction": "spin_right", "degrees": 360}, CFG).duration_s * 1000 <= CFG["max_duration_ms"]


def test_parse_request():
    assert parse_request(json.dumps({"op": "status"}).encode()) == {"op": "status"}
    for bad in (b"not json", b"[]", b'{"op": "dance"}', b"\xff", b"{" + b" " * 5000 + b"}"):
        with pytest.raises(RequestError):
            parse_request(bad)


def test_precheck():
    ok = {"state": "fault", "estop": {"latched": False}}
    assert precheck(ok, 0.3, CFG) is None
    assert precheck({"estop": {"latched": True}}, 0.3, CFG) == "estop"
    assert precheck(None, None, CFG) == "governor_unavailable"
    assert precheck(ok, 5.0, CFG) == "governor_unavailable"


def st(state, reason, vx=0.0, wz=0.0):
    return {"state": state, "reason": reason, "out": {"vx": vx, "vy": 0.0, "wz": wz}}


def test_summarize_clamped_move():
    p = Plan(0.4, 0.0, 1.0)
    s = summarize([st("fault", "heartbeat_timeout"), st("limited", "clamped", 0.2), st("ok", "ok")], p)
    assert s["moved"] and s["clamped"] and not s["blocked"]
    assert s["max_out"] == {"vx": 0.2, "wz": 0.0}


def test_summarize_blocked():
    p = Plan(0.1, 0.0, 1.0)
    s = summarize([st("limited", "obstacle"), st("limited", "obstacle"), st("idle", "cmd_timeout")], p)
    assert s["blocked"] and s["blocked_reason"] == "obstacle" and not s["moved"]
    s = summarize([st("estop", "estop")], p)
    assert s["blocked"] and s["blocked_reason"] == "estop"
    assert summarize([], p)["blocked"] is False  # no status seen: unknown, not claimed blocked


def test_summarize_stopped_midway():
    s = summarize([st("ok", "ok", 0.1), st("limited", "obstacle")], Plan(0.1, 0.0, 1.0))
    assert s["moved"] and not s["blocked"] and s["stopped_by"] == "obstacle"
