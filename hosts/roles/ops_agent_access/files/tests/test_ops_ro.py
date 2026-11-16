"""ops-ro dispatcher and ops-ro-root helper: parsing, validation, redaction, cap, rate limit (no host commands).

Fake secrets are assembled at run time so the repo's secret scanners don't flag this file.
"""

import datetime
import hashlib
import importlib.util
import os
import pathlib
import random
import string

import pytest

FILES = pathlib.Path(__file__).resolve().parents[1]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ops = _load(FILES / "ops-ro.py", "ops_ro")
root = _load(FILES / "ops-ro-root.py", "ops_ro_root")
NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)


def rand(n, alphabet=string.ascii_letters + string.digits, seed=1):
    rng = random.Random(seed)
    while True:
        s = "".join(rng.choice(alphabet) for _ in range(n))
        want = [cls for cls in (str.islower, str.isupper, str.isdigit) if any(cls(c) for c in alphabet)]
        if all(any(cls(c) for c in s) for cls in want):
            return s


# ------------------------------------------------------------------ parsing

@pytest.mark.parametrize("command,verb,args", [
    ("help", "help", []),
    ("health", "health", []),
    ("units", "units", []),
    ("status ssh", "status", ["ssh"]),
    ("status getty@tty1.service", "status", ["getty@tty1.service"]),
    ("journal sshd -2h", "journal", ["sshd", "2026-11-16 10:00:00 UTC"]),
    ("journal k3s -30m", "journal", ["k3s", "2026-11-16 11:30:00 UTC"]),
    ("journal k3s -7d", "journal", ["k3s", "2026-11-09 12:00:00 UTC"]),
    ("journal k3s 2026-11-16T10:00Z", "journal", ["k3s", "2026-11-16 10:00:00 UTC"]),
    ("journal k3s 2026-11-16T02:00:00-08:00", "journal", ["k3s", "2026-11-16 10:00:00 UTC"]),
    ("journal k3s '2026-11-16 10:00:00'", "journal", ["k3s", "2026-11-16 10:00:00 UTC"]),
    ("kernel -1d", "kernel", ["2026-11-15 12:00:00 UTC"]),
    ("kernel-prev", "kernel-prev", []),
    ("containers", "containers", []),
    ("container-logs observe_grafana-1", "container-logs", ["observe_grafana-1"]),
    ("gpu", "gpu", []),
    ("net", "net", []),
    ("k3s", "k3s", []),
    ("k3s -6h", "k3s", ["2026-11-16 06:00:00 UTC"]),
    ("certs", "certs", []),
    ("defenseclaw", "defenseclaw", []),
])
def test_parse_accepts_the_allowlist(command, verb, args):
    assert ops.parse(command, NOW) == (verb, args)


@pytest.mark.parametrize("command", [
    None,                                # interactive shell (no command)
    "",
    "   ",
    "env",
    "cat /etc/shadow",
    "status ssh; id",                    # ';' becomes part of a word: too many args
    "status 'ssh;id'",                   # bad unit name
    "journal ssh -1h; rm -rf /",
    "journal ssh -1h && reboot",
    "container-logs x --follow",
    "container-logs x -f",
    "reboot",
    "systemctl reboot",
    "status",                            # missing unit
    "status ssh extra",
    "status -Hroot@evil",                # option injection
    "status --help",
    "status .hidden",
    "status ../../etc/passwd",
    "status " + "a" * 65,
    "journal ssh 2h",                    # since without '-'
    "journal ssh -8d",                   # more than 7 days
    "journal ssh -200h",
    "journal ssh -0h",
    "journal ssh 2026-11-01T00:00Z",     # more than 7 days back
    "journal ssh 2027-01-01T00:00Z",     # future
    "journal ssh 2026-13-45T00:00Z",     # invalid date
    "journal ssh 'yesterday'",
    "journal ssh '-1h --output=export'",
    "kernel",
    "kernel-prev -1",
    "containers -a",
    "docker inspect x",
    "exec x",
    "help me",
    "health $(id)",
    "status `id`",
    "status ssh\nid",
    "status 'ssh\x00'",
    "status \"unterminated",
    "x" * 300,
])
def test_parse_refuses_everything_else(command):
    with pytest.raises(ops.Refused):
        ops.parse(command, NOW)


def test_help_lists_every_verb_and_nothing_that_changes_state():
    rc, text = ops.execute("help", [])
    assert rc == 0
    for verb in ops.VERBS:
        assert verb in text
    for bad in ("restart", "reboot", "exec", "inspect", "env", "rm"):
        assert bad not in ops.VERBS


# ------------------------------------------------------------------ redaction

def red(text):
    return ops.redact(text)[0]


def test_pem_private_key_blocks_are_removed_even_when_cut_off():
    body = "\n".join(rand(64, seed=i) for i in range(5))
    for kind in ("", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED "):
        block = f"-----BEGIN {kind}PRIVATE KEY-----\n{body}\n-----END {kind}PRIVATE KEY-----"
        out = red(f"before\n{block}\nafter")
        assert body.splitlines()[0] not in out and "before" in out and "after" in out
    cut = red("x\n-----BEGIN OPENSSH PRIVATE KEY-----\n" + body[:100])
    assert body[:40] not in cut


def test_authorization_and_bearer_headers():
    tok = rand(40, seed=2)
    for line in (f"Authorization: Bearer {tok}", f"authorization: Basic {tok}", f"'Authorization': '{tok}'",
                 f"curl -H \"Authorization: Bearer {tok}\"", f"Bearer {tok}", f"X-Api-Key: {tok}"):
        out = red(line)
        assert tok not in out, line
        assert "[REDACTED]" in out


@pytest.mark.parametrize("name", ["password", "PASSWORD", "db_password", "token", "api_key", "apikey", "API-KEY",
                                  "secret", "client_secret", "access_key", "LITELLM_MASTER_KEY", "passphrase",
                                  "credentials"])
@pytest.mark.parametrize("sep", ["=", ": ", "=\"", "\": \""])
def test_key_value_secrets(name, sep):
    value = "hunter2" + rand(6, seed=3)
    out = red(f"x {name}{sep}{value} y")
    assert value not in out and "[REDACTED]" in out


def test_urls_with_credentials_keep_user_and_host():
    pw = "pa" + rand(10, seed=4)
    out = red(f"postgres://app:{pw}@db.local:5432/x and https://u:{pw}@example.com/")
    assert pw not in out
    assert "postgres://app:[REDACTED]@db.local:5432/x" in out


def test_vendor_key_shapes():
    keys = [
        "AKIA" + rand(16, string.ascii_uppercase + string.digits, seed=5),
        "sk-" + rand(48, seed=6),
        "sk-proj-" + rand(40, seed=7),
        "ghp_" + rand(36, seed=8),
        "github_pat_" + rand(60, seed=9),
        "xoxb-" + rand(30, seed=10),
        "eyJ" + rand(20, seed=11) + ".eyJ" + rand(30, seed=12) + "." + rand(30, seed=13),
    ]
    for k in keys:
        out = red(f"value {k} end")
        assert k not in out, k


def test_high_entropy_strings():
    hexkey = hashlib.sha256(b"x").hexdigest()
    b64 = rand(44, string.ascii_letters + string.digits + "+/", seed=14) + "="
    for s in (hexkey, hexkey[:32], b64, rand(32, seed=15)):
        out = red(f"start {s} end")
        assert s not in out, s


@pytest.mark.parametrize("text", [
    "image ghcr.io/x/y@sha256:" + hashlib.sha256(b"d").hexdigest(),
    "/var/lib/rancher/k3s/server/tls/serving-kube-apiserver.crt",
    "/opt/homelab/jobs/admin-tools/tls/admin-tools.crt",
    "pod 0f8fad5b-d9cb-469f-a165-70867728950e restarted",
    "pocket-id-token-sync.service: Deactivated successfully.",
    "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE",
    "k3s-agent.service - Lightweight Kubernetes",
    "Nov 16 10:00:00 dgx-1 sshd[123]: Accepted publickey for nikghodki-dgx from 192.168.86.44 port 5 ssh2",
    "observe_grafana-1\tUp 3 hours (healthy)\tgrafana/grafana:12.3.0",
    "Accepted key ED25519 SHA256:" + "Zx9" + "a" * 20 + "B7qK" * 5 + " found at /var/lib/opsro/.ssh/authorized_keys:1",
    "/var/lib/rancher/k3s/data/" + hashlib.sha256(b"k").hexdigest() + "/bin/containerd-shim-runc-v2",
    " Invocation: " + hashlib.md5(b"i").hexdigest(),
    "max_tokens=500",
])
def test_ordinary_output_is_kept(text):
    assert red(text) == text


def test_redaction_counts():
    _, n = ops.redact("password=a1 token=b2 nothing here")
    assert n == 2


# ------------------------------------------------------------------ cap

def test_cap_limits_to_64k_and_says_truncated():
    out = ops.cap("é" * 100000)
    assert len(out.encode()) <= 64 * 1024
    assert out.endswith("[truncated]\n")
    assert ops.cap("short") == "short"


# ------------------------------------------------------------------ rate limit

def test_rate_limit_60_per_minute(tmp_path):
    t = 1000.0
    for i in range(60):
        assert not ops.rate_limited(now=t + i * 0.1, directory=str(tmp_path))
    assert ops.rate_limited(now=t + 7, directory=str(tmp_path))
    assert not ops.rate_limited(now=t + 61, directory=str(tmp_path))


def test_rate_limit_fails_closed_without_its_folder(tmp_path):
    assert ops.rate_limited(directory=str(tmp_path / "missing"))


# ------------------------------------------------------------------ defenseclaw summary

def test_defenseclaw_summary_has_states_not_config():
    data = {"uptime_ms": 5000, "provenance": {"binary_version": "1.0.9", "content_hash": "abc"},
            "api": {"state": "running", "details": {"addr": "127.0.0.1:18970"}},
            "guardrail": {"state": "disabled", "last_error": "no connector configured"},
            "config": {"state": "running", "details": {"path": "/home/x/.defenseclaw/config.yaml"}},
            "policy": {"generation": 1, "built_at": "2026-11-16T03:59:57Z", "effective_digest": "d"},
            "connectors": [{"name": "agent-gateway", "state": "running", "requests": 63, "errors": 0}]}
    text = "\n".join(ops.summarise_defenseclaw(data))
    assert "api: running" in text and "guardrail: disabled (last_error: no connector configured)" in text
    assert "version=1.0.9" in text and "connector name=agent-gateway state=running requests=63" in text
    assert ".defenseclaw" not in text and "18970" not in text and "content_hash" not in text


# ------------------------------------------------------------------ root helper

@pytest.mark.parametrize("argv", [[], ["env"], ["containers", "x"], ["container-logs"], ["container-logs", "-f"],
                                  ["container-logs", "x", "--follow"], ["container-logs", "a;b"], ["certs", "/x"],
                                  ["inspect", "x"], ["exec", "x", "sh"]])
def test_root_helper_refuses(argv):
    with pytest.raises(root.Refused):
        root.dispatch(argv)


@pytest.mark.parametrize("path,ok", [
    ("/opt/homelab/bus/nats/certs/nats.crt", True),
    ("/var/lib/rancher/k3s/server/tls/client-auth-proxy.crt", True),
    ("/usr/local/share/ca-certificates/homelab-ca.crt", True),
    ("/opt/homelab/bus/nats/certs/nats.key", False),
    ("/opt/homelab/bus/nats/certs/nats-key.pem", False),
    ("/etc/ssh/ssh_host_ed25519_key.pub", False),
    ("/home/x/.ssh/id_ed25519.pem", False),
    ("/home/x/.defenseclaw/ca.crt", False),
    ("/srv/secrets/ca.crt", False),
    ("/etc/shadow", False),
    ("/opt/x/../../etc/shadow.crt", False),
    ("relative/ca.crt", False),
    ("/opt/app/.env", False),
    ("/opt/app/token.pem", False),
])
def test_cert_paths(path, ok):
    assert (root.cert_path_ok(path) is None) is ok


def test_cert_list_must_be_root_owned(tmp_path):
    f = tmp_path / "certs"
    f.write_text("/opt/a.crt\n")
    if os.getuid() != 0:
        with pytest.raises(root.Refused):
            root.read_cert_list(str(f))


def test_not_after_days():
    now = datetime.datetime(2026, 11, 16)
    assert root.not_after_days("notAfter=Nov 26 00:00:00 2026 GMT\n", now) == 10
    assert root.not_after_days("garbage", now) is None


def test_helper_name_validation_matches_dispatcher():
    for name in ("observe_grafana-1", "a", "x@y.z"):
        assert root.valid_name(name) == ops.valid_name(name)
    for name in ("-f", ".x", "a b", "a;b", "a" * 65):
        with pytest.raises(root.Refused):
            root.valid_name(name)
        with pytest.raises(ops.Refused):
            ops.valid_name(name)


def test_jetson_gpu_from_sysfs(tmp_path):
    gpu = tmp_path / "devices/platform/bus@0/17000000.gpu"
    gpu.mkdir(parents=True)
    (gpu / "load").write_text("125\n")
    dev = tmp_path / "class/devfreq/17000000.gpu"
    dev.mkdir(parents=True)
    (dev / "cur_freq").write_text("306000000\n")
    zone = tmp_path / "class/thermal/thermal_zone1"
    zone.mkdir(parents=True)
    (zone / "type").write_text("gpu-thermal\n")
    (zone / "temp").write_text("49906\n")
    out = ops.jetson_gpu(str(tmp_path))
    assert "utilization.gpu=12.5%" in out and "cur_freq=306 MHz" in out and "gpu-thermal=49.9C" in out
