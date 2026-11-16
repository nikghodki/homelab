#!/usr/bin/python3 -I
"""ops-ro-root: the root half of ops-ro (decision 0013). Called only as `sudo -n ops-ro-root <verb> [arg]`.

It re-validates its arguments itself and runs exactly these, never through a shell:
  containers                 docker ps -a --format '{{.Names}}\\t{{.Status}}\\t{{.Image}}'
  container-logs <name>      docker logs --tail 300 --timestamps <name>   (an existing container's name only)
  certs                      openssl x509 -noout -subject -enddate for each path in /etc/ops-agent/certs
No docker inspect or exec, no env, no arbitrary file reads. The caller (ops-ro) redacts and caps the output.
Exit codes: 0 ran, 1 a command failed, 2 refused.
Managed by homelab Ansible (hosts/roles/ops_agent_access). Python 3 standard library only.
"""

import datetime
import os
import re
import shutil
import stat
import subprocess
import sys

SAFE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8"}
NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9@._-]{0,63}$")
CERTS_LIST = "/etc/ops-agent/certs"
MAX_READ = 512 * 1024
TIMEOUT = 30
CERT_SUFFIXES = (".crt", ".pem", ".cert", ".cer")
# Never read anything that looks like a key or a secret, even if it is listed (design §3.2)
DENY_RE = re.compile(r"(?i)(key|token|secret|passw|credential|\.env$|/\.ssh/|^/etc/ssh/|\.defenseclaw|/secrets?/|"
                     r"/shadow|/gshadow|/proc/|/sys/|/dev/)")


class Refused(Exception):
    pass


def valid_name(value):
    if not NAME_RE.match(value or ""):
        raise Refused("invalid container name")
    return value


def cert_path_ok(path):
    """A listed path must be absolute, normalised, end like a certificate and not look like a key or a secret."""
    if not path.startswith("/") or os.path.normpath(path) != path or "\x00" in path:
        return "not an absolute normalised path"
    if not path.endswith(CERT_SUFFIXES):
        return "not a certificate file name (.crt/.pem/.cert/.cer)"
    if DENY_RE.search(path):
        return "looks like a key or secret path"
    real = os.path.realpath(path)
    if real != path and (DENY_RE.search(real) or not real.endswith(CERT_SUFFIXES)):
        return "resolves to a key-like or non-certificate path"
    return None


def run(argv):
    try:
        res = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=SAFE_ENV, timeout=TIMEOUT, check=False, shell=False)  # noqa: S603 - fixed argv
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or b"")[:MAX_READ].decode("utf-8", "replace") + "\n[timed out]\n"
    except OSError as exc:
        return 127, f"cannot run {argv[0]}: {exc.strerror}\n"
    out = res.stdout[:MAX_READ].decode("utf-8", "replace")
    if len(res.stdout) > MAX_READ:
        out += "\n[truncated]\n"
    return res.returncode, out


def docker():
    return shutil.which("docker", path=SAFE_ENV["PATH"])


def list_containers():
    exe = docker()
    if not exe:
        return 0, "docker is not installed on this host\n"
    return run([exe, "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"])


def container_logs(name):
    exe = docker()
    if not exe:
        return 0, "docker is not installed on this host\n"
    rc, names = run([exe, "ps", "-a", "--format", "{{.Names}}"])
    if rc != 0:
        return rc, names
    if name not in names.split():
        raise Refused(f"no container named {name!r}")
    return run([exe, "logs", "--tail", "300", "--timestamps", name])


def not_after_days(text, now=None):
    m = re.search(r"notAfter=(.+)", text)
    if not m:
        return None
    try:
        when = datetime.datetime.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z")
    except ValueError:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return (when - now).days


def read_cert_list(path=CERTS_LIST):
    st = os.stat(path)
    if st.st_uid != 0 or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise Refused(f"{path} must be root-owned and not group/world-writable")
    with open(path, encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip() and not line.lstrip().startswith("#")]


def certs():
    try:
        paths = read_cert_list()
    except FileNotFoundError:
        return 0, "no certificates are listed for this host\n"
    exe = shutil.which("openssl", path=SAFE_ENV["PATH"])
    if not exe:
        return 1, "openssl is not installed\n"
    lines, worst = [], 0
    for path in paths[:100]:
        why = cert_path_ok(path)
        if why:
            lines.append(f"{path}\trefused: {why}")
            continue
        try:
            st = os.stat(path)
        except FileNotFoundError:
            lines.append(f"{path}\tmissing")
            continue
        if not stat.S_ISREG(st.st_mode) or st.st_size > 1024 * 1024:
            lines.append(f"{path}\trefused: not a regular file under 1 MB")
            continue
        rc, out = run([exe, "x509", "-noout", "-subject", "-enddate", "-in", path])
        if rc != 0:
            worst = 1
            lines.append(f"{path}\tnot a certificate (openssl exit {rc})")
            continue
        subject = re.search(r"subject=\s*(.+)", out)
        end = re.search(r"notAfter=(.+)", out)
        days = not_after_days(out)
        lines.append(f"{path}\tnotAfter={end.group(1).strip() if end else '?'}\tdays_left={days}\t"
                     f"subject={subject.group(1).strip() if subject else '?'}")
    return worst, "\n".join(lines) + "\n"


def dispatch(argv):
    if argv == ["containers"]:
        return list_containers()
    if len(argv) == 2 and argv[0] == "container-logs":
        return container_logs(valid_name(argv[1]))
    if argv == ["certs"]:
        return certs()
    raise Refused("allowed: containers | container-logs <name> | certs")


def main():
    try:
        rc, out = dispatch(sys.argv[1:])
    except Refused as exc:
        sys.stdout.write(f"refused: {exc}\n")
        return 2
    sys.stdout.write(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
