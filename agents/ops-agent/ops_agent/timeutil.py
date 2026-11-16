"""Times as the tools accept them: RFC 3339, 'now', or relative ('-2h', '-30m', '-1d', '+10m'), always UTC."""
from __future__ import annotations

import datetime as dt
import re

UTC = dt.timezone.utc
_REL = re.compile(r"^(now)?\s*([+-])\s*(\d+)\s*([smhd])$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MAX_RANGE = dt.timedelta(days=7)


def now() -> dt.datetime:
    return dt.datetime.now(UTC)


def parse(s: str | None, base: dt.datetime) -> dt.datetime | None:
    if s is None or s == "":
        return None
    s = str(s).strip()
    if s == "now":
        return base
    m = _REL.match(s)
    if m:
        secs = int(m.group(3)) * _UNIT[m.group(4)]
        return base + dt.timedelta(seconds=secs if m.group(2) == "+" else -secs)
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def window(start: str | None, end: str | None, as_of: dt.datetime | None, default: dt.timedelta) -> tuple[dt.datetime, dt.datetime]:
    """Resolve a [start, end] window. In replay (as_of set) nothing after as_of is visible; ranges cap at 7 days."""
    base = as_of or now()
    e = parse(end, base) or base
    if as_of is not None and e > as_of:
        e = as_of
    s = parse(start, base) or (e - default)
    if s > e:
        s = e - default
    if e - s > MAX_RANGE:
        s = e - MAX_RANGE
    return s, e


def iso(t: dt.datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def local(t: dt.datetime, tz: str = "America/Los_Angeles") -> str:
    from zoneinfo import ZoneInfo
    return t.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M %Z")
