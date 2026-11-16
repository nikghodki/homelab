"""Pure logic of the motion bridge (no ROS, no sockets), so CI can test it.

The bridge turns the car-style requests of picoclaw's MCP server (drive/turn with speed 0-255,
direction, duration) into a timed stream of geometry_msgs/Twist on /cmd_vel_in plus heartbeats on
/safety/heartbeat: the safety governor's inputs. The bridge is not a safety layer; the governor
clamps, rejects and stops. The bridge only refuses requests it cannot express, and refuses to start
a move while the governor reports a latched e-stop or is not reporting at all.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

DEFAULTS = {
    "socket": "/run/robot-motion/motion.sock",
    "socket_mode": 0o660,  # owner and group (robot-motion); set through the umask at bind
    "cmd_topic": "/cmd_vel_in",
    "heartbeat_topic": "/safety/heartbeat",
    "status_topic": "/safety/status",
    "estop_topic": "/safety/estop",
    "cmd_rate_hz": 10.0,
    "heartbeat_rate_hz": 5.0,
    "default_duration_ms": 1000,
    "max_duration_ms": 10000,
    # speed 255 maps to these. Above the governor's caps (it clamps) and below its ceiling (it would reject).
    "full_speed_linear": 0.4,
    "full_speed_angular": 2.0,
    "turn_rate": 0.8,  # rad/s for turn by degrees (open loop, like the firmware's /turn)
    "status_max_age_s": 2.0,  # no governor status this recent -> refuse to move
    "estop_on_stop": True,  # the stop op latches the governor's e-stop (cleared by a human: safety-reset)
    "ceiling_linear": 0.5,
    "ceiling_angular": 2.5,
}
DIRECTIONS = {
    "forward": (1.0, 0.0),
    "backward": (-1.0, 0.0),
    "spin_left": (0.0, 1.0),
    "spin_right": (0.0, -1.0),
}
STRAFE = ("strafe_left", "strafe_right")
OPS = ("drive", "turn", "move", "halt", "stop", "status")
MAX_REQUEST_BYTES = 4096


class RequestError(ValueError):
    """A request the bridge refuses before anything is published."""


@dataclass(frozen=True)
class Plan:
    vx: float
    wz: float
    duration_s: float

    def as_dict(self) -> dict:
        return {"vx": round(self.vx, 4), "wz": round(self.wz, 4), "duration_s": round(self.duration_s, 3)}


def load_config(raw: dict) -> dict:
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown motion bridge config keys: {sorted(unknown)}")
    cfg = {**DEFAULTS, **raw}
    if not 0 < cfg["full_speed_linear"] < cfg["ceiling_linear"]:
        raise ValueError("full_speed_linear must be above 0 and below ceiling_linear (the governor would reject it)")
    if not 0 < cfg["full_speed_angular"] < cfg["ceiling_angular"]:
        raise ValueError("full_speed_angular must be above 0 and below ceiling_angular")
    if not 0 < cfg["turn_rate"] < cfg["ceiling_angular"]:
        raise ValueError("turn_rate must be above 0 and below ceiling_angular")
    if not 0 < cfg["default_duration_ms"] <= cfg["max_duration_ms"]:
        raise ValueError("default_duration_ms must be in (0, max_duration_ms]")
    if not isinstance(cfg["socket_mode"], int) or cfg["socket_mode"] & ~0o666:
        raise ValueError("socket_mode must be read/write bits only, e.g. 0o660")
    if cfg["cmd_rate_hz"] < 4 or cfg["heartbeat_rate_hz"] < 1:
        raise ValueError("cmd_rate_hz must be >= 4 (governor command timeout 0.5 s), heartbeat_rate_hz >= 1")
    return cfg


def _number(req: dict, key: str, default=None) -> float:
    value = req.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RequestError(f"{key} must be a finite number")
    return float(value)


def _duration(req: dict, cfg: dict) -> float:
    ms = req.get("duration_ms")
    if ms is None:
        ms = cfg["default_duration_ms"]
    ms = _number({"duration_ms": ms}, "duration_ms")
    if not 0 < ms <= cfg["max_duration_ms"]:
        raise RequestError(f"duration_ms must be in (0, {cfg['max_duration_ms']}]")
    return ms / 1000.0


def plan(req: dict, cfg: dict) -> Plan:
    """Translate a drive/turn/move request into a Twist held for a duration."""
    op = req.get("op")
    if op == "drive":
        direction = req.get("direction")
        if direction in STRAFE:
            raise RequestError("strafing is not supported: the governor allows no sideways motion (allow_strafe false)")
        if direction not in DIRECTIONS:
            raise RequestError(f"direction must be one of {sorted(DIRECTIONS)}")
        speed = _number(req, "speed", 180)
        if not 0 <= speed <= 255:
            raise RequestError("speed must be 0-255")
        sx, sw = DIRECTIONS[direction]
        frac = speed / 255.0
        return Plan(sx * frac * cfg["full_speed_linear"], sw * frac * cfg["full_speed_angular"], _duration(req, cfg))
    if op == "turn":
        direction = req.get("direction")
        if direction not in ("spin_left", "spin_right"):
            raise RequestError("direction must be spin_left or spin_right")
        degrees = _number(req, "degrees")
        if not 0 < degrees <= 360:
            raise RequestError("degrees must be in (0, 360]")
        duration = math.radians(degrees) / cfg["turn_rate"]
        if duration * 1000 > cfg["max_duration_ms"]:
            raise RequestError("turn would take longer than max_duration_ms")
        return Plan(0.0, DIRECTIONS[direction][1] * cfg["turn_rate"], duration)
    if op == "move":
        return Plan(_number(req, "vx", 0.0), _number(req, "wz", 0.0), _duration(req, cfg))
    raise RequestError(f"op {op!r} is not a motion op")


def parse_request(line: bytes) -> dict:
    if len(line) > MAX_REQUEST_BYTES:
        raise RequestError("request too long")
    try:
        req = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RequestError(f"request is not JSON: {exc}") from None
    if not isinstance(req, dict) or req.get("op") not in OPS:
        raise RequestError(f"op must be one of {list(OPS)}")
    return req


def precheck(status: dict | None, status_age_s: float | None, cfg: dict) -> str | None:
    """Reason to refuse a move before publishing anything, or None."""
    if status is None or status_age_s is None or status_age_s > cfg["status_max_age_s"]:
        return "governor_unavailable"
    if status.get("estop", {}).get("latched"):
        return "estop"
    return None


def _moving(out: dict) -> bool:
    return any(abs(float(out.get(k, 0.0))) > 1e-9 for k in ("vx", "vy", "wz"))


def summarize(statuses: list[dict], p: Plan) -> dict:
    """What the governor did with a move, from the /safety/status messages seen while it ran."""
    states: dict[str, int] = {}
    max_out = {"vx": 0.0, "wz": 0.0}
    moved = False
    stops: dict[str, int] = {}
    for st in statuses:
        key = f"{st.get('state')}/{st.get('reason')}"
        states[key] = states.get(key, 0) + 1
        out = st.get("out") or {}
        if _moving(out):
            moved = True
            for k in max_out:
                if abs(out.get(k, 0.0)) > abs(max_out[k]):
                    max_out[k] = out.get(k, 0.0)
        elif st.get("reason") not in ("ok", "cmd_timeout"):
            stops[st.get("reason")] = stops.get(st.get("reason"), 0) + 1
    blocked = bool(statuses) and not moved
    reason = max(stops, key=stops.get) if stops else None
    clamped = any(st.get("reason") == "clamped" for st in statuses)
    return {
        "commanded": p.as_dict(),
        "governor_states": states,
        "moved": moved,
        "max_out": max_out,
        "clamped": clamped,
        "blocked": blocked,
        "blocked_reason": reason if blocked else None,
        "stopped_by": reason if moved and reason else None,
        "status_messages": len(statuses),
    }
