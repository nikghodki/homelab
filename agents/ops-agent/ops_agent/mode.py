"""Effective mode: the most restrictive of the database switch (portal Stop) and Git (agents/ops-agent/mode.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml

from . import db
from .config import settings

ORDER = {"stopped": 0, "shadow": 1}


def git_mode() -> str:
    p = Path(settings().mode_file)
    try:
        m = (yaml.safe_load(p.read_text()) or {}).get("mode", "shadow")
    except FileNotFoundError:
        return "shadow"
    except Exception:
        return "stopped"  # unreadable kill switch: fail closed
    return m if m in ORDER else "stopped"


def effective() -> str:
    try:
        d = db.db_mode()
    except Exception:
        return "stopped"  # no database: nothing runs
    return min((git_mode(), d), key=lambda m: ORDER.get(m, 0))


def running() -> bool:
    return effective() != "stopped"
