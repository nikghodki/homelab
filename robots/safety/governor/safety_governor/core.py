"""Safety governor logic: plain Python, no ROS or NATS imports.

Every input is passed in with a timestamp (monotonic seconds), and `step(now)` returns the
velocity the motors may get right now. The checks, in order of precedence (the first one that
applies decides):

1. e-stop latched                        -> zero (state "estop")
2. no LiDAR scan, scan stale or unusable -> zero (state "fault")
3. no heartbeat from the commanding side -> zero (state "fault")
4. no fresh command                      -> zero (state "idle")
5. command not finite or above ceiling   -> zero (state "rejected")
6. obstacle in the direction of travel   -> translation zeroed (state "limited")
7. command above the speed caps          -> clamped (state "limited")
8. otherwise                             -> passed through (state "ok")

The e-stop is latched: only `reset()` clears it, and after a reset only commands received
*after* the reset count, so a stale command can't move the robot the moment the latch opens.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields

STATE_ESTOP = "estop"
STATE_FAULT = "fault"
STATE_IDLE = "idle"
STATE_REJECTED = "rejected"
STATE_LIMITED = "limited"
STATE_OK = "ok"

REASON_ESTOP = "estop"
REASON_SCAN_STALE = "scan_stale"
REASON_SCAN_INVALID = "scan_invalid"
REASON_HEARTBEAT = "heartbeat_timeout"
REASON_CMD_TIMEOUT = "cmd_timeout"
REASON_INVALID = "invalid_command"
REASON_CEILING = "above_ceiling"
REASON_OBSTACLE = "obstacle"
REASON_CLAMPED = "clamped"
REASON_OK = "ok"

# Reasons that make the output zero although a command may be asking for motion.
STOP_REASONS = frozenset(
    {REASON_ESTOP, REASON_SCAN_STALE, REASON_SCAN_INVALID, REASON_HEARTBEAT, REASON_INVALID, REASON_CEILING}
)


@dataclass(frozen=True)
class Velocity:
    """Body-frame velocity: vx forward (m/s), vy left (m/s), wz counter-clockwise (rad/s)."""

    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0

    def is_zero(self) -> bool:
        return self.vx == 0.0 and self.vy == 0.0 and self.wz == 0.0

    def is_finite(self) -> bool:
        return all(math.isfinite(v) for v in (self.vx, self.vy, self.wz))

    def as_dict(self) -> dict:
        return {"vx": self.vx, "vy": self.vy, "wz": self.wz}


ZERO = Velocity()


@dataclass(frozen=True)
class Scan:
    """The parts of a sensor_msgs/LaserScan the governor needs."""

    angle_min: float
    angle_increment: float
    ranges: tuple
    range_min: float
    range_max: float


@dataclass(frozen=True)
class Config:
    # Speed caps: commands are clamped to these (m/s, rad/s).
    max_linear: float = 0.20
    max_angular: float = 1.0
    # Absolute ceiling: a command above this is rejected outright (zero), not clamped.
    ceiling_linear: float = 0.50
    ceiling_angular: float = 2.5
    # Sideways motion (vy). Off: vy is forced to 0 (the car's /velocity API has no strafe).
    allow_strafe: bool = False
    # Obstacle stop: no translation towards anything closer than stop_distance (m) inside
    # +-sector_half_width_deg of the direction of travel.
    stop_distance: float = 0.35
    sector_half_width_deg: float = 35.0
    # Robot bearing (deg, CCW from forward) of the LiDAR's angle 0; 0 when the LiDAR faces forward.
    lidar_yaw_deg: float = 0.0
    # Ranges below this are the robot's own body, not obstacles (m).
    self_filter_radius: float = 0.08
    # Turning in place stays allowed when translation is blocked.
    allow_rotation_when_blocked: bool = True
    # A scan with fewer valid ranges than this fraction counts as a fault (blocked or broken LiDAR). 0 = off.
    min_valid_fraction: float = 0.2
    # Watchdogs (s).
    heartbeat_timeout: float = 2.0
    heartbeat_required: bool = True
    cmd_timeout: float = 0.5
    scan_timeout: float = 1.0

    def __post_init__(self) -> None:
        positive = (
            "max_linear",
            "max_angular",
            "ceiling_linear",
            "ceiling_angular",
            "stop_distance",
            "heartbeat_timeout",
            "cmd_timeout",
            "scan_timeout",
        )
        for name in positive:
            value = getattr(self, name)
            if not (isinstance(value, (int, float)) and math.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be a positive number, got {value!r}")
        if self.max_linear > self.ceiling_linear:
            raise ValueError("max_linear must not exceed ceiling_linear")
        if self.max_angular > self.ceiling_angular:
            raise ValueError("max_angular must not exceed ceiling_angular")
        if not 0 < self.sector_half_width_deg <= 180:
            raise ValueError("sector_half_width_deg must be in (0, 180]")
        if not 0 <= self.min_valid_fraction <= 1:
            raise ValueError("min_valid_fraction must be in [0, 1]")
        if self.self_filter_radius < 0:
            raise ValueError("self_filter_radius must be >= 0")

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown safety limit(s): {', '.join(sorted(unknown))}")
        return cls(**data)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Decision:
    out: Velocity
    state: str
    reason: str
    detail: str = ""


def normalize_angle(a: float) -> float:
    """Angle in (-pi, pi]."""
    a = math.fmod(a, 2 * math.pi)
    if a <= -math.pi:
        a += 2 * math.pi
    elif a > math.pi:
        a -= 2 * math.pi
    return a


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


class Governor:
    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.estop_latched = False
        self.estop_source: str | None = None
        self.estop_since: float | None = None
        self._scan_t: float | None = None
        self._points: list[tuple[float, float]] = []  # (robot bearing rad, range m)
        self._scan_valid = False
        self._valid_fraction = 0.0
        self._hb_t: float | None = None
        self._cmd: Velocity | None = None
        self._cmd_t: float | None = None
        self._last: Decision | None = None
        self.last_stop_reason: str | None = None
        self.last_stop_detail: str = ""
        self.last_stop_t: float | None = None
        self.interventions: dict[str, int] = {}
        self._events: list[dict] = []

    # ---- inputs -------------------------------------------------------------------------

    def estop(self, now: float, source: str) -> bool:
        """Latch the e-stop. Returns True if it wasn't latched before."""
        if self.estop_latched:
            return False
        self.estop_latched = True
        self.estop_source = source
        self.estop_since = now
        self._event(now, "estop", REASON_ESTOP, f"latched by {source}")
        return True

    def reset(self, now: float, source: str) -> bool:
        """Clear the e-stop. Returns True if it was latched. Commands from before the reset are dropped."""
        if not self.estop_latched:
            return False
        self.estop_latched = False
        self._event(now, "reset", REASON_ESTOP, f"cleared by {source} (latched by {self.estop_source})")
        self.estop_source = None
        self.estop_since = None
        self._cmd = None
        self._cmd_t = None
        return True

    def heartbeat(self, now: float) -> None:
        self._hb_t = now

    def command(self, now: float, cmd: Velocity) -> None:
        self._cmd = cmd
        self._cmd_t = now

    def scan(self, now: float, scan: Scan) -> None:
        cfg = self.cfg
        yaw = math.radians(cfg.lidar_yaw_deg)
        floor = max(scan.range_min, cfg.self_filter_radius)
        points = []
        for i, r in enumerate(scan.ranges):
            if r is None or not math.isfinite(r) or r < floor or r > scan.range_max:
                continue
            points.append((normalize_angle(scan.angle_min + i * scan.angle_increment + yaw), float(r)))
        total = len(scan.ranges)
        self._valid_fraction = (len(points) / total) if total else 0.0
        self._scan_valid = total > 0 and self._valid_fraction >= cfg.min_valid_fraction
        self._points = points
        self._scan_t = now

    # ---- queries ------------------------------------------------------------------------

    def nearest_in_sector(self, bearing: float, half_width: float) -> float | None:
        best = None
        for b, r in self._points:
            if abs(normalize_angle(b - bearing)) <= half_width and (best is None or r < best):
                best = r
        return best

    def step(self, now: float) -> Decision:
        decision = self._decide(now)
        self._account(now, decision)
        self._last = decision
        return decision

    def pop_events(self) -> list[dict]:
        events, self._events = self._events, []
        return events

    def status(self, now: float) -> dict:
        def age(t):
            return None if t is None else round(now - t, 3)

        last = self._last
        quarter = math.pi / 4
        nearest = {
            name: self.nearest_in_sector(b, quarter)
            for name, b in (("front", 0.0), ("left", math.pi / 2), ("back", math.pi), ("right", -math.pi / 2))
        }
        return {
            "state": last.state if last else STATE_FAULT,
            "reason": last.reason if last else REASON_SCAN_STALE,
            "detail": last.detail if last else "",
            "out": (last.out if last else ZERO).as_dict(),
            "estop": {
                "latched": self.estop_latched,
                "source": self.estop_source,
                "age_s": age(self.estop_since),
            },
            "last_stop": {
                "reason": self.last_stop_reason,
                "detail": self.last_stop_detail,
                "age_s": age(self.last_stop_t),
            },
            "ages_s": {"scan": age(self._scan_t), "heartbeat": age(self._hb_t), "cmd": age(self._cmd_t)},
            "scan_valid_fraction": round(self._valid_fraction, 3),
            "nearest_m": {k: (None if v is None else round(v, 3)) for k, v in nearest.items()},
            "interventions": dict(self.interventions),
            "limits": self.cfg.as_dict(),
        }

    # ---- internals ----------------------------------------------------------------------

    def _decide(self, now: float) -> Decision:
        cfg = self.cfg
        if self.estop_latched:
            return Decision(ZERO, STATE_ESTOP, REASON_ESTOP, f"latched by {self.estop_source}")
        if self._scan_t is None or now - self._scan_t > cfg.scan_timeout:
            detail = "no scan yet" if self._scan_t is None else f"last scan {now - self._scan_t:.2f}s ago"
            return Decision(ZERO, STATE_FAULT, REASON_SCAN_STALE, detail)
        if not self._scan_valid:
            return Decision(
                ZERO, STATE_FAULT, REASON_SCAN_INVALID, f"only {self._valid_fraction:.0%} of the ranges are valid"
            )
        if cfg.heartbeat_required and (self._hb_t is None or now - self._hb_t > cfg.heartbeat_timeout):
            detail = "no heartbeat yet" if self._hb_t is None else f"last heartbeat {now - self._hb_t:.2f}s ago"
            return Decision(ZERO, STATE_FAULT, REASON_HEARTBEAT, detail)
        if self._cmd is None or now - self._cmd_t > cfg.cmd_timeout:
            detail = "no command" if self._cmd is None else f"last command {now - self._cmd_t:.2f}s ago"
            return Decision(ZERO, STATE_IDLE, REASON_CMD_TIMEOUT, detail)

        cmd = self._cmd
        if not cmd.is_finite():
            return Decision(ZERO, STATE_REJECTED, REASON_INVALID, f"non-finite command {cmd.as_dict()}")
        if abs(cmd.vx) > cfg.ceiling_linear or abs(cmd.vy) > cfg.ceiling_linear or abs(cmd.wz) > cfg.ceiling_angular:
            return Decision(
                ZERO,
                STATE_REJECTED,
                REASON_CEILING,
                f"command {cmd.as_dict()} above ceiling {cfg.ceiling_linear} m/s / {cfg.ceiling_angular} rad/s",
            )

        vy = cmd.vy if cfg.allow_strafe else 0.0
        vx = _clamp(cmd.vx, cfg.max_linear)
        vy = _clamp(vy, cfg.max_linear)
        wz = _clamp(cmd.wz, cfg.max_angular)
        clamped = (vx, vy, wz) != (cmd.vx, cmd.vy, cmd.wz)

        if vx != 0.0 or vy != 0.0:
            heading = math.atan2(vy, vx)
            nearest = self.nearest_in_sector(heading, math.radians(cfg.sector_half_width_deg))
            if nearest is not None and nearest < cfg.stop_distance:
                out = Velocity(0.0, 0.0, wz if cfg.allow_rotation_when_blocked else 0.0)
                return Decision(
                    out,
                    STATE_LIMITED,
                    REASON_OBSTACLE,
                    f"obstacle at {nearest:.2f} m towards {math.degrees(heading):.0f} deg (stop at {cfg.stop_distance} m)",
                )

        out = Velocity(vx, vy, wz)
        if clamped:
            return Decision(out, STATE_LIMITED, REASON_CLAMPED, f"command {cmd.as_dict()} clamped to {out.as_dict()}")
        return Decision(out, STATE_OK, REASON_OK)

    def _account(self, now: float, d: Decision) -> None:
        prev = self._last
        if prev is not None and prev.reason == d.reason:
            return
        was_moving = prev is not None and not prev.out.is_zero()
        stopping = d.reason in STOP_REASONS or d.reason == REASON_OBSTACLE
        watchdog = d.reason == REASON_CMD_TIMEOUT and was_moving
        if stopping or watchdog:
            self.last_stop_reason = d.reason
            self.last_stop_detail = d.detail
            self.last_stop_t = now
        if stopping or watchdog or d.reason == REASON_CLAMPED:
            self.interventions[d.reason] = self.interventions.get(d.reason, 0) + 1
            self._event(now, "intervention", d.reason, d.detail, out=d.out)

    def _event(self, now: float, kind: str, reason: str, detail: str, out: Velocity | None = None) -> None:
        event = {"t": now, "kind": kind, "reason": reason, "detail": detail}
        if out is not None:
            event["out"] = out.as_dict()
        self._events.append(event)
