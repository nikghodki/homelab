import datetime as dt

from ops_agent import notify

UTC = dt.timezone.utc


def at(h, m):  # a PST time on 2026-11-16 as UTC (PST = UTC-8)
    return dt.datetime(2026, 11, 16, h, m, tzinfo=dt.timezone(dt.timedelta(hours=-8))).astimezone(UTC)


def test_quiet_hours():
    assert notify.in_quiet_hours(at(23, 0)) and notify.in_quiet_hours(at(7, 0))
    assert not notify.in_quiet_hours(at(7, 31)) and not notify.in_quiet_hours(at(22, 29))


def test_decisions():
    assert notify.decide("rca", "warning", True, at(3, 0))[0] == "send"      # family-facing: always (Q10)
    assert notify.decide("rca", "critical", False, at(12, 0))[0] == "send"
    assert notify.decide("rca", "critical", False, at(23, 30))[0] == "held"
    assert notify.decide("rca", "warning", False, at(12, 0))[0] == "held"    # shadow: digest
