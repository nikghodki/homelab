#!/usr/bin/python3 -I
"""ops-ro: SSH forced-command dispatcher for the ops agent's read-only user `opsro` (decision 0013).

sshd runs this for every connection of the `opsro` key (`restrict,command="/usr/local/sbin/ops-ro"`).
It reads SSH_ORIGINAL_COMMAND, accepts only the verbs below with fixed argument shapes, runs fixed argv lists
(never a shell), redacts the output and caps it at 64 KB. Every call is logged to the journal (tag ops-ro) with
the verb, arguments, exit code and output size, never the output. At most 60 calls a minute per host.

Exit codes: 0 ran, 1 a command could not run, 2 refused (unknown verb or bad arguments), 3 rate limited.
Managed by homelab Ansible (hosts/roles/ops_agent_access). Python 3 standard library only.
"""

import datetime
import fcntl
import http.client
import json
import math
import os
import re
import selectors
import shlex
import shutil
import subprocess
import sys
import time

MAX_OUTPUT = 64 * 1024
MAX_READ = 512 * 1024          # per command, before redaction
MAX_COMMAND = 256              # length of SSH_ORIGINAL_COMMAND
CMD_TIMEOUT = 30
RATE_LIMIT = 60                # calls per window per host
RATE_WINDOW = 60.0
RATE_DIR = "/run/ops-ro"
MAX_SINCE = datetime.timedelta(days=7)
ROOT_HELPER = "/usr/local/libexec/ops-ro-root"
CONF_DIR = "/etc/ops-agent"
SAFE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8", "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0", "NO_COLOR": "1"}

NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9@._-]{0,63}$")
REL_RE = re.compile(r"^-([1-9][0-9]{0,4})([smhd])$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class Refused(Exception):
    """The request is not on the allowlist (exit 2)."""


# ---------------------------------------------------------------- validation

def valid_name(value, what="name"):
    """Unit and container names: ^[a-zA-Z0-9@._-]{1,64}$, never starting with '-' or '.' (no option injection)."""
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise Refused(f"invalid {what} {value[:70]!r}: use 1-64 of [a-zA-Z0-9@._-], starting with a letter or digit")
    return value


def parse_since(value, now=None):
    """`-30m`, `-2h`, `-1d` (at most 7 days back) or an ISO date/time (naive = UTC) -> 'YYYY-MM-DD HH:MM:SS UTC'."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(value, str):
        raise Refused("invalid since")
    m = REL_RE.match(value)
    if m:
        delta = datetime.timedelta(seconds=int(m.group(1)) * UNIT_SECONDS[m.group(2)])
        if delta > MAX_SINCE:
            raise Refused(f"since {value!r} is more than 7 days back")
        when = now - delta
    elif ISO_RE.match(value):
        text = value.replace(" ", "T")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            when = datetime.datetime.fromisoformat(text)
        except ValueError:
            raise Refused(f"invalid since {value!r}") from None
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        if when < now - MAX_SINCE:
            raise Refused(f"since {value!r} is more than 7 days back")
        if when > now + datetime.timedelta(minutes=5):
            raise Refused(f"since {value!r} is in the future")
    else:
        raise Refused(f"invalid since {value[:40]!r}: use -30m, -2h, -1d (max 7d) or an ISO time like 2026-11-16T10:00Z")
    return when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# verb -> (argument kinds, help text). Kinds: "unit", "container", "since"; "since?" is optional.
VERBS = {
    "help": ((), "list the verbs"),
    "health": ((), "uptime, memory, disks, failed units, reboot-required"),
    "units": ((), "running and failed services"),
    "status": (("unit",), "status <unit>: systemctl status, no log lines"),
    "journal": (("unit", "since"), "journal <unit> <since>: last 500 lines since -30m/-2h/-1d/ISO (max 7d)"),
    "kernel": (("since",), "kernel <since>: kernel log, last 500 lines"),
    "kernel-prev": ((), "kernel log of the previous boot, last 500 lines"),
    "containers": ((), "docker containers: name, status, image"),
    "container-logs": (("container",), "container-logs <container>: last 300 lines with timestamps"),
    "gpu": ((), "GPU summary and compute processes (hosts with nvidia-smi)"),
    "net": ((), "addresses, routes, listening TCP ports (no process names), Tailscale peers"),
    "k3s": (("since?",), "k3s [<since>]: k3s service status and journal (default -1h)"),
    "certs": ((), "expiry of the certificates listed in /etc/ops-agent/certs"),
    "defenseclaw": ((), "DefenseClaw gateway health summary on loopback (hosts listed in /etc/ops-agent/defenseclaw)"),
}


def parse(command, now=None):
    """SSH_ORIGINAL_COMMAND -> (verb, [validated args]). Raises Refused for anything off the allowlist."""
    if command is None or not command.strip():
        raise Refused("interactive sessions are not allowed; run `help` for the verbs")
    if len(command) > MAX_COMMAND:
        raise Refused("command too long")
    if any(ord(c) < 32 and c not in " \t" for c in command):
        raise Refused("control characters are not allowed")
    try:
        words = shlex.split(command)
    except ValueError as exc:
        raise Refused(f"cannot parse command: {exc}") from None
    if not words:
        raise Refused("empty command")
    verb, args = words[0], words[1:]
    if verb not in VERBS:
        raise Refused(f"unknown verb {verb[:40]!r}; allowed: {', '.join(VERBS)}")
    kinds = VERBS[verb][0]
    required = [k for k in kinds if not k.endswith("?")]
    if not len(required) <= len(args) <= len(kinds):
        shape = " ".join(f"<{k.rstrip('?')}>" if not k.endswith("?") else f"[<{k[:-1]}>]" for k in kinds)
        raise Refused(f"usage: {verb} {shape}".rstrip())
    out = []
    for kind, value in zip(kinds, args):
        kind = kind.rstrip("?")
        if kind in ("unit", "container"):
            out.append(valid_name(value, kind))
        elif kind == "since":
            out.append(parse_since(value, now))
    return verb, out


# ---------------------------------------------------------------- redaction

R = "[REDACTED]"
_PEM = re.compile(r"-----BEGIN [^\n-]*PRIVATE KEY[^\n-]*-----.*?(?:-----END [^\n-]*PRIVATE KEY[^\n-]*-----|\Z)", re.S)
_AUTH_HDR = re.compile(r"(?i)\b((?:proxy-)?authorization|x-api-key|api-key|cookie|set-cookie)(\"?'?\s*[:=]\s*\"?'?)"
                       r"(?:(bearer|basic|token|digest|negotiate)\s+)?[^\s\"',;]+")
_BEARER = re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/=-]{12,}")
_KV = re.compile(r"(?i)\b([A-Za-z0-9_.-]*(?:passw(?:or)?d|passphrase|token|secret|api[_-]?key|access[_-]?key|"
                 r"private[_-]?key|[_-]key|credentials?)s?)(\"?'?\s*[=:]\s*\"?'?)([^\s\"'&,;}<>]+)")
_URL_CRED = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.-]{1,20}://)([^/\s:@\"']*):([^/\s@\"']+)@")
_AWS = re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA|AROA|AIDA)[A-Z0-9]{16}\b")
_SK = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")
_TOKENS = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|xox[abposr]-[A-Za-z0-9-]{10,}|"
                     r"glpat-[A-Za-z0-9_-]{20,}|tskey-[A-Za-z0-9-]{16,}|AIza[0-9A-Za-z_-]{35})")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_HEX = re.compile(r"(?<![A-Za-z0-9])(?<!sha256:)(?<!sha512:)(?<!Invocation: )[0-9a-fA-F]{32,}(?![A-Za-z0-9])")
_B64 = re.compile(r"(?<![A-Za-z0-9+/_=-])(?<!SHA256:)(?<!SHA512:)[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/_=-])")


def _entropy(s):
    counts = {}
    for c in s:
        counts[c] = counts.get(c, 0) + 1
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def _looks_random(s, min_entropy):
    classes = sum(bool(re.search(p, s)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]"))
    return classes == 3 and _entropy(s) >= min_entropy


def _b64_secret(match):
    s = match.group(0)
    core = s.rstrip("=")
    if core.startswith("/"):
        # an absolute path: redact only if one of its segments is itself a long random string
        hit = any(len(seg) >= 24 and _looks_random(seg, 3.8) for seg in core.split("/"))
        return R if hit else s
    return R if _looks_random(core, 4.0) else s


def _hex_secret(match):
    s = match.group(0)
    text, start, end = match.string, match.start(), match.end()
    if start > 0 and text[start - 1] == "/" and text[end:end + 1] == "/":
        return s  # a path segment (k3s data dir, containerd bundle): an ID, not a key
    return R if _entropy(s.lower()) >= 3.0 else s


def redact(text):
    """Redact secrets from command output. Returns (text, number of redactions)."""
    count = 0

    def sub(pattern, repl, s):
        nonlocal count
        new, n = pattern.subn(repl, s)
        if callable(repl):
            n = sum(1 for m in pattern.finditer(s) if repl(m) != m.group(0))
        count += n
        return new

    text = sub(_PEM, "[REDACTED PRIVATE KEY]", text)
    text = sub(_URL_CRED, lambda m: m.group(1) + m.group(2) + ":" + R + "@", text)
    text = sub(_AUTH_HDR, lambda m: m.group(1) + m.group(2) + (m.group(3) + " " if m.group(3) else "") + R, text)
    text = sub(_BEARER, lambda m: m.group(1) + " " + R, text)
    text = sub(_KV, lambda m: m.group(0) if m.group(3) == R or re.fullmatch(r"[0-9]{1,8}", m.group(3))
               else m.group(1) + m.group(2) + R, text)
    text = sub(_AWS, R, text)
    text = sub(_SK, R, text)
    text = sub(_TOKENS, R, text)
    text = sub(_JWT, R, text)
    text = sub(_HEX, _hex_secret, text)
    text = sub(_B64, _b64_secret, text)
    return text, count


def cap(text, limit=MAX_OUTPUT):
    """Cap the UTF-8 size at `limit` bytes, ending with [truncated]."""
    data = text.encode("utf-8", "replace")
    if len(data) <= limit:
        return text
    marker = "\n[truncated]\n"
    return data[: limit - len(marker)].decode("utf-8", "ignore") + marker


# ---------------------------------------------------------------- running commands

def run(argv, timeout=CMD_TIMEOUT):
    """Run a fixed argv (no shell), stdout+stderr, at most MAX_READ bytes. Returns (exit code, text)."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=SAFE_ENV, close_fds=True, shell=False)  # noqa: S603 - fixed argv
    except OSError as exc:
        return 127, f"cannot run {argv[0]}: {exc.strerror}\n"
    deadline = time.monotonic() + timeout
    chunks, size, note = [], 0, b""
    fd = proc.stdout.fileno()
    with selectors.DefaultSelector() as sel:
        sel.register(fd, selectors.EVENT_READ)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                note = b"\n[timed out]\n"
                break
            if not sel.select(left):
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_READ:
                note = b"\n[truncated]\n"
                break
    if note:
        proc.kill()
    proc.stdout.close()
    try:
        rc = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = proc.wait()
    return rc, (b"".join(chunks)[:MAX_READ] + note).decode("utf-8", "replace")


def section(title, argv):
    rc, out = run(argv)
    head = f"## {title}" + ("" if rc == 0 else f" (exit {rc})")
    return rc, f"{head}\n{out}" + ("" if out.endswith("\n") or not out else "\n")


def run_sections(items):
    parts, worst = [], 0
    for title, argv in items:
        rc, text = section(title, argv)
        parts.append(text)
        if rc == 127:
            worst = 1
    return worst, "".join(parts)


def have(binary):
    return shutil.which(binary, path=SAFE_ENV["PATH"]) is not None


def root_helper(*args):
    return ["sudo", "-n", ROOT_HELPER, *args]


def k3s_unit():
    for unit in ("k3s", "k3s-agent"):
        for d in ("/etc/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system"):
            if os.path.exists(os.path.join(d, unit + ".service")):
                return unit
    return None


def tailscale_peers():
    if not have("tailscale"):
        return 0, "## tailscale\nnot installed\n"
    rc, out = run(["tailscale", "status", "--json"])
    if rc != 0:
        return 0, f"## tailscale (exit {rc})\n{out[:2000]}\n"
    try:
        data = json.loads(out)
    except ValueError:
        return 0, "## tailscale\nunreadable status\n"
    nodes = [data.get("Self") or {}] + list((data.get("Peer") or {}).values())
    lines = ["## tailscale (HostName DNSName Online OS)"]
    for n in nodes:
        lines.append("\t".join(str(n.get(k, "")) for k in ("HostName", "DNSName", "Online", "OS")))
    return 0, "\n".join(lines) + "\n"


def defenseclaw_summary():
    path = os.path.join(CONF_DIR, "defenseclaw")
    try:
        with open(path, encoding="utf-8") as fh:
            ports = [line.strip() for line in fh if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        return 0, "no DefenseClaw gateway is listed for this host\n"
    parts = []
    for port in ports:
        if not re.fullmatch(r"[1-9][0-9]{1,4}", port) or int(port) > 65535:
            parts.append(f"## 127.0.0.1:{port[:8]}\ninvalid port in {path}\n")
            continue
        conn = http.client.HTTPConnection("127.0.0.1", int(port), timeout=5)
        try:
            conn.request("GET", "/health")
            data = json.loads(conn.getresponse().read(MAX_READ).decode("utf-8", "replace"))
        except (OSError, ValueError, http.client.HTTPException) as exc:
            parts.append(f"## 127.0.0.1:{port}/health\nunreachable: {type(exc).__name__}\n")
            continue
        finally:
            conn.close()
        parts.append(f"## 127.0.0.1:{port}/health\n" + "\n".join(summarise_defenseclaw(data)) + "\n")
    return 0, "".join(parts)


def summarise_defenseclaw(data):
    """State and counters only: never config paths, policy content or destinations."""
    lines = []
    if not isinstance(data, dict):
        return ["unexpected health payload"]
    prov = data.get("provenance") or {}
    lines.append(f"version={prov.get('binary_version', '?')} uptime_s={int((data.get('uptime_ms') or 0) / 1000)}")
    for key in sorted(data):
        val = data[key]
        if isinstance(val, dict) and "state" in val:
            err = val.get("last_error")
            lines.append(f"{key}: {val.get('state')}" + (f" (last_error: {str(err)[:120]})" if err else ""))
    pol = data.get("policy") or {}
    if isinstance(pol, dict):
        lines.append("policy: " + " ".join(f"{k}={pol.get(k)}" for k in ("generation", "config_generation",
                                                                          "built_at", "component_count") if k in pol))
    for c in data.get("connectors") or []:
        if isinstance(c, dict):
            lines.append("connector " + " ".join(f"{k}={c.get(k)}" for k in (
                "name", "state", "requests", "errors", "tool_blocks", "tool_inspections", "subprocess_blocks")))
    return lines


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read(4096).strip()
    except OSError:
        return None


def jetson_gpu(sysfs="/sys"):
    """Jetson (Tegra): GPU load, clock and temperatures from world-readable sysfs, unified memory from meminfo."""
    lines = ["## gpu (Jetson sysfs)"]
    load = _read(f"{sysfs}/devices/platform/bus@0/17000000.gpu/load") or _read(f"{sysfs}/devices/platform/gpu.0/load")
    if load and load.isdigit():
        lines.append(f"utilization.gpu={int(load) / 10:.1f}%")
    for name in ("cur_freq", "max_freq"):
        val = _read(f"{sysfs}/class/devfreq/17000000.gpu/{name}")
        if val and val.isdigit():
            lines.append(f"{name}={int(val) // 1000000} MHz")
    zones = sorted(os.listdir(f"{sysfs}/class/thermal")) if os.path.isdir(f"{sysfs}/class/thermal") else []
    for zone in zones:
        kind = _read(f"{sysfs}/class/thermal/{zone}/type")
        temp = _read(f"{sysfs}/class/thermal/{zone}/temp")
        if kind and temp and temp.lstrip("-").isdigit():
            lines.append(f"{kind}={int(temp) / 1000:.1f}C")
    mem = {}
    for line in (_read("/proc/meminfo") or "").splitlines():
        key, _, rest = line.partition(":")
        if key in ("MemTotal", "MemAvailable"):
            mem[key] = int(rest.split()[0]) // 1024
    if mem:
        lines.append(f"memory (unified) total={mem.get('MemTotal')} MiB available={mem.get('MemAvailable')} MiB")
    return "\n".join(lines) + "\n"


def execute(verb, args):
    """Run a validated verb. Returns (exit code, output text before redaction)."""
    if verb == "help":
        width = max(map(len, VERBS))
        return 0, "".join(f"{v.ljust(width)}  {VERBS[v][1]}\n" for v in VERBS)
    if verb == "health":
        rc, text = run_sections([
            ("uptime", ["uptime"]),
            ("free -m", ["free", "-m"]),
            ("df", ["df", "-hT", "-x", "tmpfs", "-x", "overlay", "-x", "devtmpfs", "-x", "squashfs"]),
            ("failed units", ["systemctl", "--failed", "--no-legend", "--no-pager", "--plain"]),
        ])
        reboot = "yes" if os.path.exists("/run/reboot-required") else "no"
        return rc, text + f"## reboot-required\n{reboot}\n"
    if verb == "units":
        return run_sections([("running and failed services", ["systemctl", "list-units", "--type=service",
                                                               "--state=running,failed", "--no-legend",
                                                               "--no-pager", "--plain"])])
    if verb == "status":
        return run_sections([(f"status {args[0]}", ["systemctl", "status", "--no-pager", "-n", "0", "--", args[0]])])
    if verb == "journal":
        return run_sections([(f"journal {args[0]} since {args[1]}",
                              ["journalctl", "-u", args[0], f"--since={args[1]}", "-n", "500", "-o", "short-iso",
                               "--no-pager", "-q"])])
    if verb == "kernel":
        return run_sections([(f"kernel since {args[0]}", ["journalctl", "-k", f"--since={args[0]}", "-n", "500",
                                                          "-o", "short-iso", "--no-pager", "-q"])])
    if verb == "kernel-prev":
        return run_sections([("kernel, previous boot", ["journalctl", "-k", "-b", "-1", "-n", "500", "-o",
                                                        "short-iso", "--no-pager", "-q"])])
    if verb == "containers":
        return run_sections([("containers", root_helper("containers"))])
    if verb == "container-logs":
        return run_sections([(f"container-logs {args[0]}", root_helper("container-logs", args[0]))])
    if verb == "gpu":
        if os.path.exists("/etc/nv_tegra_release"):
            return 0, jetson_gpu()
        if not have("nvidia-smi"):
            return 0, "no nvidia-smi on this host\n"
        return run_sections([
            ("gpu", ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,"
                                   "power.draw,clocks.sm", "--format=csv"]),
            ("compute apps", ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv"]),
        ])
    if verb == "net":
        rc, text = run_sections([
            ("ip -br addr", ["ip", "-br", "addr"]),
            ("ip route", ["ip", "route"]),
            ("ss -tlnH", ["ss", "-tlnH"]),
        ])
        _, ts = tailscale_peers()
        return rc, text + ts
    if verb == "k3s":
        unit = k3s_unit()
        if unit is None:
            return 0, "k3s is not installed on this host\n"
        since = args[0] if args else parse_since("-1h")
        return run_sections([
            (f"status {unit}", ["systemctl", "status", "--no-pager", "-n", "0", "--", unit]),
            (f"journal {unit} since {since}", ["journalctl", "-u", unit, f"--since={since}", "-n", "300", "-o",
                                               "short-iso", "--no-pager", "-q"]),
        ])
    if verb == "certs":
        return run_sections([("certs", root_helper("certs"))])
    if verb == "defenseclaw":
        return defenseclaw_summary()
    raise Refused(f"unknown verb {verb!r}")  # unreachable: parse() checked it


# ---------------------------------------------------------------- rate limit and audit log

def rate_limited(now=None, directory=RATE_DIR, limit=RATE_LIMIT, window=RATE_WINDOW):
    """True if this call is over the limit. Counts every call (refused ones too). Fails closed."""
    now = time.time() if now is None else now
    try:
        fd = os.open(os.path.join(directory, "calls"), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return True
    with os.fdopen(fd, "r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            stamps = [float(x) for x in fh.read().split()]
        except ValueError:
            stamps = []
        stamps = [t for t in stamps if now - window < t <= now]
        over = len(stamps) >= limit
        if not over:
            stamps.append(now)
        fh.seek(0)
        fh.truncate()
        fh.write("\n".join(f"{t:.3f}" for t in stamps))
    return over


def audit(verb, args, rc, nbytes, redactions=0, note=""):
    src = (os.environ.get("SSH_CONNECTION") or "-").split(" ")[0]
    safe_verb = re.sub(r"[^a-zA-Z0-9@._-]", "?", verb)[:40] or "-"
    msg = (f"verb={safe_verb} args={','.join(args) if args else '-'} exit={rc} bytes={nbytes} "
           f"redactions={redactions} from={src}" + (f" {note}" if note else ""))
    try:
        subprocess.run(["logger", "-t", "ops-ro", "--", msg], env=SAFE_ENV, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def main():
    command = os.environ.get("SSH_ORIGINAL_COMMAND")
    first = (command or "").split(" ", 1)[0] if command else "-"
    if rate_limited():
        sys.stdout.write("refused: rate limit (60 calls a minute on this host); try again shortly\n")
        audit(first, [], 3, 0, note="refused=rate_limit")
        return 3
    try:
        verb, args = parse(command)
    except Refused as exc:
        sys.stdout.write(f"refused: {exc}\n")
        audit(first, [], 2, 0, note="refused=allowlist")
        return 2
    rc, text = execute(verb, args)
    text, redactions = redact(text)
    text = cap(text)
    data = text.encode("utf-8", "replace")
    sys.stdout.buffer.write(data)
    sys.stdout.flush()
    audit(verb, args, rc, len(data), redactions)
    return rc


if __name__ == "__main__":
    sys.exit(main())
