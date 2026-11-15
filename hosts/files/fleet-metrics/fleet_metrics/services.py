"""Per-host service enumeration: allow-listed systemd units + auto-discovered
docker containers + ollama models. Each probe is best-effort; a missing tool
contributes nothing and never raises."""
import logging
import subprocess

logger = logging.getLogger(__name__)


def _unit_status(unit: str, user: bool, run) -> str | None:
    cmd = ["systemctl"] + (["--user"] if user else []) + ["is-active", unit]
    try:
        r = run(cmd, capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _units(unit_names: list[str], run) -> list[dict]:
    out = []
    for unit in unit_names:
        detail = _unit_status(unit, user=False, run=run)
        if detail in (None, "inactive", "failed", "unknown"):
            user_detail = _unit_status(unit, user=True, run=run)
            if user_detail is not None:
                detail = user_detail
        detail = detail or "unknown"
        out.append({"name": unit, "kind": "unit", "up": detail == "active", "detail": detail})
    return out


def _docker(run) -> list[dict]:
    try:
        r = run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}"],
                capture_output=True, text=True, timeout=4)
        if r.returncode != 0:
            return []
        out = []
        for line in r.stdout.strip().splitlines():
            if not line.strip():
                continue
            name, _, rest = line.partition("\t")
            state, _, status = rest.partition("\t")
            out.append({"name": name, "kind": "docker", "up": state == "running", "detail": status})
        return out
    except (OSError, subprocess.SubprocessError):
        logger.info("docker not available; skipping docker services")
        return []


def _ollama(run) -> list[dict]:
    try:
        r = run(["ollama", "ps"], capture_output=True, text=True, timeout=4)
        if r.returncode != 0:
            return []
        lines = r.stdout.strip().splitlines()
        out = []
        for line in lines[1:]:  # skip header
            name = line.split()[0] if line.split() else None
            if name:
                out.append({"name": name, "kind": "ollama", "up": True, "detail": "running"})
        return out
    except (OSError, subprocess.SubprocessError):
        return []


def collect_services(units: list[str], run=subprocess.run) -> list[dict]:
    return _units(units, run) + _docker(run) + _ollama(run)
