"""Unit tests for the pure governor logic. Standard library + pytest only."""

import math
import pathlib

import pytest

from safety_governor import core
from safety_governor.core import ZERO, Config, Governor, Scan, Velocity

N = 360


def scan(near=None, near_dist=0.2, far=3.0, width_deg=10, n=N):
    """A 360-ray scan, angle 0 = forward. `near` = bearing (deg) of an obstacle at near_dist."""
    ranges = []
    for i in range(n):
        deg = i * 360.0 / n
        if near is not None and abs((deg - near + 180) % 360 - 180) <= width_deg:
            ranges.append(near_dist)
        else:
            ranges.append(far)
    return Scan(0.0, 2 * math.pi / n, tuple(ranges), 0.05, 20.0)


def ready(cfg=None, now=0.0, **scan_kw):
    """A governor with a fresh far scan and a heartbeat at `now`."""
    g = Governor(cfg or Config())
    g.scan(now, scan(**scan_kw))
    g.heartbeat(now)
    return g


def drive(g, now, cmd):
    g.command(now, cmd)
    return g.step(now)


# ---- config ---------------------------------------------------------------------------


def test_default_config_is_valid_and_strict():
    cfg = Config()
    assert cfg.heartbeat_timeout == 2.0
    assert cfg.max_linear <= cfg.ceiling_linear


@pytest.mark.parametrize(
    "bad",
    [
        {"max_linear": 0.6, "ceiling_linear": 0.5},
        {"max_angular": 3.0, "ceiling_angular": 2.0},
        {"stop_distance": 0},
        {"heartbeat_timeout": -1},
        {"scan_timeout": float("nan")},
        {"sector_half_width_deg": 0},
        {"min_valid_fraction": 1.5},
    ],
)
def test_bad_config_rejected(bad):
    with pytest.raises(ValueError):
        Config.from_dict(bad)


def test_unknown_limit_rejected():
    with pytest.raises(ValueError, match="unknown"):
        Config.from_dict({"max_speed": 1})


def test_shipped_limits_file_is_valid():
    yaml = pytest.importorskip("yaml")
    path = pathlib.Path(__file__).resolve().parents[2] / "limits.yaml"
    cfg = Config.from_dict(yaml.safe_load(path.read_text()))
    assert cfg.heartbeat_timeout <= 2.0
    assert cfg.scan_timeout <= 1.0


# ---- pass-through and clamping --------------------------------------------------------


def test_clean_command_passes_through():
    g = ready()
    d = drive(g, 0.0, Velocity(0.1, 0.0, 0.3))
    assert d.state == core.STATE_OK
    assert d.out == Velocity(0.1, 0.0, 0.3)


def test_clamped_to_speed_caps():
    g = ready()
    d = drive(g, 0.0, Velocity(0.45, 0.0, -2.0))
    assert d.reason == core.REASON_CLAMPED
    assert d.out == Velocity(0.2, 0.0, -1.0)
    d = drive(g, 0.0, Velocity(-0.3, 0.0, 1.5))
    assert d.out == Velocity(-0.2, 0.0, 1.0)


def test_strafe_forced_to_zero_unless_allowed():
    d = drive(ready(), 0.0, Velocity(0.0, 0.1, 0.0))
    assert d.out == ZERO and d.reason == core.REASON_CLAMPED
    d = drive(ready(Config(allow_strafe=True)), 0.0, Velocity(0.0, 0.3, 0.0))
    assert d.out == Velocity(0.0, 0.2, 0.0)


@pytest.mark.parametrize(
    "cmd", [Velocity(0.51, 0, 0), Velocity(-0.6, 0, 0), Velocity(0, 0, 2.6), Velocity(0, 0, -3.0)]
)
def test_above_ceiling_rejected(cmd):
    d = drive(ready(), 0.0, cmd)
    assert d.state == core.STATE_REJECTED and d.reason == core.REASON_CEILING
    assert d.out == ZERO


def test_strafe_above_ceiling_rejected_even_when_strafe_disabled():
    d = drive(ready(), 0.0, Velocity(0.0, 0.9, 0.0))
    assert d.reason == core.REASON_CEILING and d.out == ZERO


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_rejected(bad):
    d = drive(ready(), 0.0, Velocity(bad, 0.0, 0.0))
    assert d.reason == core.REASON_INVALID and d.out == ZERO


# ---- obstacle sector ------------------------------------------------------------------


def test_obstacle_ahead_blocks_forward():
    g = ready(near=0)
    d = drive(g, 0.0, Velocity(0.1, 0.0, 0.0))
    assert d.reason == core.REASON_OBSTACLE and d.out == ZERO


def test_obstacle_ahead_allows_reversing_away():
    g = ready(near=0)
    d = drive(g, 0.0, Velocity(-0.1, 0.0, 0.0))
    assert d.state == core.STATE_OK and d.out == Velocity(-0.1, 0.0, 0.0)


def test_obstacle_behind_blocks_reverse_not_forward():
    g = ready(near=180)
    assert drive(g, 0.0, Velocity(-0.1, 0, 0)).out == ZERO
    assert drive(g, 0.0, Velocity(0.1, 0, 0)).out == Velocity(0.1, 0, 0)


def test_obstacle_to_the_side_does_not_block_forward():
    g = ready(near=90)
    assert drive(g, 0.0, Velocity(0.1, 0, 0)).out == Velocity(0.1, 0, 0)


def test_sector_edges():
    # Default half width 35 deg; obstacle 10 deg wide centered at 40 deg -> edge at 30 deg: inside.
    assert drive(ready(near=40), 0.0, Velocity(0.1, 0, 0)).out == ZERO
    # Centered at 50 deg -> nearest edge at 40 deg: outside.
    assert drive(ready(near=50), 0.0, Velocity(0.1, 0, 0)).out == Velocity(0.1, 0, 0)
    # Negative bearings (right side, scan angle ~330 deg).
    assert drive(ready(near=330), 0.0, Velocity(0.1, 0, 0)).out == ZERO


def test_obstacle_beyond_stop_distance_is_ignored():
    g = ready(near=0, near_dist=0.5)
    assert drive(g, 0.0, Velocity(0.1, 0, 0)).out == Velocity(0.1, 0, 0)


def test_rotation_allowed_when_blocked_unless_configured():
    d = drive(ready(near=0), 0.0, Velocity(0.1, 0.0, 0.5))
    assert d.out == Velocity(0.0, 0.0, 0.5) and d.reason == core.REASON_OBSTACLE
    d = drive(ready(Config(allow_rotation_when_blocked=False), near=0), 0.0, Velocity(0.1, 0.0, 0.5))
    assert d.out == ZERO


def test_pure_rotation_not_blocked_by_obstacle():
    d = drive(ready(near=0), 0.0, Velocity(0.0, 0.0, 0.5))
    assert d.out == Velocity(0.0, 0.0, 0.5) and d.state == core.STATE_OK


def test_lidar_yaw_offset_rotates_the_sector():
    # The LiDAR is mounted facing backwards: its angle 0 is the robot's 180 deg.
    g = ready(Config(lidar_yaw_deg=180.0), near=180)  # obstacle at LiDAR 180 = robot forward
    assert drive(g, 0.0, Velocity(0.1, 0, 0)).out == ZERO
    assert drive(g, 0.0, Velocity(-0.1, 0, 0)).out == Velocity(-0.1, 0, 0)


def test_strafe_direction_uses_side_sector():
    g = ready(Config(allow_strafe=True), near=90)
    assert drive(g, 0.0, Velocity(0.0, 0.1, 0.0)).out == ZERO  # left is blocked
    assert drive(g, 0.0, Velocity(0.0, -0.1, 0.0)).out == Velocity(0.0, -0.1, 0.0)


def test_invalid_ranges_are_ignored_and_self_hits_filtered():
    ranges = [3.0] * N
    ranges[0] = float("inf")
    ranges[1] = float("nan")
    ranges[2] = 0.0  # below range_min: no return
    ranges[3] = 0.06  # inside self_filter_radius: the robot's own body
    g = Governor(Config())
    g.scan(0.0, Scan(0.0, 2 * math.pi / N, tuple(ranges), 0.05, 20.0))
    g.heartbeat(0.0)
    assert drive(g, 0.0, Velocity(0.1, 0, 0)).out == Velocity(0.1, 0, 0)


def test_mostly_invalid_scan_is_a_fault():
    ranges = [float("inf")] * N
    ranges[:10] = [3.0] * 10
    g = Governor(Config())
    g.scan(0.0, Scan(0.0, 2 * math.pi / N, tuple(ranges), 0.05, 20.0))
    g.heartbeat(0.0)
    d = drive(g, 0.0, Velocity(0.1, 0, 0))
    assert d.reason == core.REASON_SCAN_INVALID and d.out == ZERO


def test_real_ms200_geometry():
    # The Pi's MS200: angle_min 0.0037, increment 0.01397, 449 ranges, 0..2pi.
    n = 449
    inc = 0.013973906636238098
    ranges = [3.0] * n
    ranges[-2] = 0.2  # just right of forward (~ -0.03 rad)
    g = Governor(Config())
    g.scan(0.0, Scan(0.003665574826300144, inc, tuple(ranges), 0.05, 20.0))
    g.heartbeat(0.0)
    assert drive(g, 0.0, Velocity(0.1, 0, 0)).out == ZERO


# ---- e-stop ---------------------------------------------------------------------------


def test_estop_latches_and_needs_reset():
    g = ready()
    assert drive(g, 0.0, Velocity(0.1, 0, 0)).out == Velocity(0.1, 0, 0)
    assert g.estop(0.1, "nats") is True
    for t in (0.1, 0.2, 0.3):
        g.scan(t, scan())
        g.heartbeat(t)
        d = drive(g, t, Velocity(0.1, 0, 0))
        assert d.state == core.STATE_ESTOP and d.out == ZERO
    assert g.estop(0.3, "ros") is False  # already latched; the first source is kept
    assert g.estop_source == "nats"
    assert g.reset(0.4, "nats") is True
    assert g.reset(0.4, "nats") is False


def test_reset_drops_commands_from_before_the_reset():
    g = ready()
    g.command(0.0, Velocity(0.1, 0, 0))
    g.estop(0.0, "ros")
    g.reset(0.1, "ros")
    d = g.step(0.1)  # the old command is gone: idle, not moving
    assert d.state == core.STATE_IDLE and d.out == ZERO
    assert drive(g, 0.2, Velocity(0.1, 0, 0)).out == Velocity(0.1, 0, 0)


def test_estop_events_and_status():
    g = ready()
    g.estop(1.0, "nats")
    g.step(1.0)
    status = g.status(1.5)
    assert status["state"] == "estop"
    assert status["estop"] == {"latched": True, "source": "nats", "age_s": 0.5}
    assert status["last_stop"]["reason"] == "estop"
    kinds = [e["kind"] for e in g.pop_events()]
    assert kinds == ["estop", "intervention"]
    assert g.pop_events() == []


# ---- watchdogs ------------------------------------------------------------------------


def test_no_scan_ever_is_a_fault():
    g = Governor(Config())
    g.heartbeat(0.0)
    d = drive(g, 0.0, Velocity(0.1, 0, 0))
    assert d.reason == core.REASON_SCAN_STALE and d.out == ZERO


def test_stale_scan_stops():
    g = ready()
    assert drive(g, 0.0, Velocity(0.1, 0, 0)).out != ZERO
    g.heartbeat(0.9)
    assert drive(g, 0.9, Velocity(0.1, 0, 0)).out != ZERO  # 0.9 s old scan: still fresh
    g.heartbeat(1.05)
    d = drive(g, 1.05, Velocity(0.1, 0, 0))
    assert d.reason == core.REASON_SCAN_STALE and d.out == ZERO
    g.scan(1.1, scan())
    assert drive(g, 1.1, Velocity(0.1, 0, 0)).out != ZERO  # recovers by itself, not latched


def test_no_heartbeat_ever_stops():
    g = Governor(Config())
    g.scan(0.0, scan())
    d = drive(g, 0.0, Velocity(0.1, 0, 0))
    assert d.reason == core.REASON_HEARTBEAT and d.out == ZERO


def test_heartbeat_timeout_is_two_seconds():
    g = ready()
    for t in (0.5, 1.0, 1.5, 2.0):
        g.scan(t, scan())
        assert drive(g, t, Velocity(0.1, 0, 0)).out != ZERO
    g.scan(2.05, scan())
    d = drive(g, 2.05, Velocity(0.1, 0, 0))
    assert d.reason == core.REASON_HEARTBEAT and d.out == ZERO


def test_heartbeat_can_be_made_optional():
    g = Governor(Config(heartbeat_required=False))
    g.scan(0.0, scan())
    assert drive(g, 0.0, Velocity(0.1, 0, 0)).out != ZERO


def test_command_timeout_stops_and_counts_as_watchdog_intervention():
    g = ready()
    drive(g, 0.0, Velocity(0.1, 0, 0))
    g.pop_events()
    assert g.step(0.5).out != ZERO
    d = g.step(0.51)
    assert d.state == core.STATE_IDLE and d.out == ZERO
    assert g.last_stop_reason == core.REASON_CMD_TIMEOUT
    assert [e["reason"] for e in g.pop_events()] == [core.REASON_CMD_TIMEOUT]


def test_idle_from_start_is_not_an_intervention():
    g = ready()
    g.step(0.0)
    assert g.pop_events() == []
    assert g.last_stop_reason is None


def test_interventions_logged_once_per_change():
    g = ready(near=0)
    for t in (0.0, 0.1, 0.2):
        g.scan(t, scan(near=0))
        drive(g, t, Velocity(0.1, 0, 0))
    assert g.interventions == {core.REASON_OBSTACLE: 1}
    assert len(g.pop_events()) == 1


# ---- precedence -----------------------------------------------------------------------


def test_precedence_estop_over_everything():
    g = Governor(Config())  # no scan, no heartbeat
    g.estop(0.0, "ros")
    g.command(0.0, Velocity(9.0, 0, 0))
    assert g.step(0.0).reason == core.REASON_ESTOP


def test_precedence_scan_over_heartbeat_over_command():
    g = Governor(Config())
    g.command(0.0, Velocity(9.0, 0, 0))
    assert g.step(0.0).reason == core.REASON_SCAN_STALE
    g.scan(0.0, scan(near=0))
    assert g.step(0.0).reason == core.REASON_HEARTBEAT
    g.heartbeat(0.0)
    assert g.step(0.0).reason == core.REASON_CEILING


def test_precedence_cmd_timeout_over_ceiling():
    g = ready()
    g.command(0.0, Velocity(9.0, 0, 0))
    assert g.step(0.6).reason == core.REASON_CMD_TIMEOUT


def test_precedence_ceiling_over_obstacle_over_clamp():
    g = ready(near=0)
    assert drive(g, 0.0, Velocity(0.6, 0, 0)).reason == core.REASON_CEILING
    assert drive(g, 0.0, Velocity(0.4, 0, 0)).reason == core.REASON_OBSTACLE
    assert drive(g, 0.0, Velocity(-0.4, 0, 0)).reason == core.REASON_CLAMPED


def test_output_never_exceeds_caps():
    cfg = Config()
    g = ready(cfg)
    vals = [-3.0, -0.5, -0.3, -0.1, 0.0, 0.1, 0.3, 0.5, 3.0]
    for vx in vals:
        for wz in vals:
            out = drive(g, 0.0, Velocity(vx, 0.0, wz)).out
            assert abs(out.vx) <= cfg.max_linear and abs(out.wz) <= cfg.max_angular and out.vy == 0.0
