import datetime as dt
import json

import pytest

from ops_agent import correlate, redact, timeutil
from ops_agent.investigate.own_loop import self_check, to_markdown
from ops_agent.playbooks import steps_for
from ops_agent.tools import hosts
from ops_agent.tools.gateway import _fmt_logs, _fmt_prom

UTC = dt.timezone.utc


def am(alerts):
    return {"version": "4", "status": "firing", "alerts": alerts}


def test_alertmanager_events_skip_watchdog_and_classify():
    body = am([
        {"status": "firing", "labels": {"alertname": "Watchdog"}, "startsAt": "2026-11-16T10:00:00Z"},
        {"status": "firing", "labels": {"alertname": "FleetMemoryLow", "host_name": "spark-83dc", "severity": "critical"},
         "annotations": {"summary": "memory low on dgx-1"}, "startsAt": "2026-11-15T22:41:12.123456789Z", "fingerprint": "abc"},
        {"status": "resolved", "labels": {"alertname": "ArgoCDAppOutOfSync", "name": "kyverno"},
         "startsAt": "2026-11-15T01:00:00Z", "endsAt": "2026-11-15T01:10:00Z"},
    ])
    evs = correlate.from_alertmanager(body)
    assert [e.labels["alertname"] for e in evs] == ["FleetMemoryLow", "ArgoCDAppOutOfSync"]
    assert evs[0].klass == "gpu_memory" and evs[0].severity == "critical"
    assert evs[0].occurred_at == dt.datetime(2026, 11, 15, 22, 41, 12, 123456, tzinfo=UTC)
    assert evs[1].klass == "argocd" and evs[1].status == "resolved"
    assert evs[0].incident_key() == "alert:FleetMemoryLow,host_name=spark-83dc"


def test_gatus_classes_and_family_impact():
    assert correlate.classify_alert("GatusEndpointFailing", {"name": "status gate refuses direct access"}) == "gatus_check"
    assert correlate.classify_alert("GatusEndpointFailing", {"name": "ha.nghodki.ai"}) == "front_door"
    assert correlate.family_impact("GatusEndpointFailing: ha.nghodki.ai failing")
    assert correlate.family_impact("webui.nghodki.ai down")
    assert not correlate.family_impact("docs build failed")


def test_k8s_events_filtered():
    base = {"type": "Warning", "reason": "BackOff", "involvedObject": {"kind": "Pod", "namespace": "edge", "name": "edge-caddy-x"},
            "message": "Back-off restarting failed container", "lastTimestamp": "2026-11-16T10:00:00Z", "count": 4}
    ev = correlate.from_k8s_event(base)
    assert ev.klass == "container_restart" and ev.incident_key() == "k8s:edge/Pod/edge-caddy-x:container_restart"
    assert correlate.from_k8s_event({**base, "type": "Normal"}) is None
    assert correlate.from_k8s_event({**base, "reason": "Unhealthy", "count": 1}) is None
    assert correlate.from_k8s_event({**base, "reason": "Scheduled"}) is None


def test_components_and_change_matching():
    comps = correlate.components_for_paths(["policies/kyverno/require-image-digest.yaml", "cluster/apps/ops/database.yaml"])
    assert comps == ["app:ops", "kyverno"]
    assert correlate.change_matches("kyverno", {}, comps)
    assert correlate.change_matches("container_restart", {"namespace": "ops"}, comps)
    assert not correlate.change_matches("gpu_memory", {}, comps)


def test_storm_detector():
    s = correlate.StormDetector(limit=3, window=60, quiet=120)
    assert not any(s.add(t) for t in (0, 1, 2))
    assert s.add(3)
    assert s.active(100)
    assert not s.active(200)


def test_redaction():
    text = ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345\npassword=hunter2hunter2 url=https://u:p4ss@host/x "
            "key sk-ABCDEFGHIJKLMNOPQRSTUVWX ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 digest sha256:" + "a" * 64 +
            "\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----")
    out, n = redact.redact(text)
    for secret in ("abcdefghijklmnopqrstuvwxyz012345", "hunter2hunter2", "p4ss", "sk-ABCDEF", "ghp_ABCDEF", "b3BlbnNzaC1rZXk"):
        assert secret not in out, secret
    assert "sha256:" + "a" * 64 in out          # digests stay
    assert n >= 6
    again, k = redact.redact(out)            # redacted text stays as it is
    assert again == out and k == 0
    assert redact.redact("see docs/secrets-rotation.md:12-20")[1] == 0
    assert redact.redact("FailedScheduling Pod/ops/ops-portal-767f685b89-b25wz: 0/4 nodes")[1] == 0
    assert redact.redact("x " + "QwErTyUiOpAsDfGhJkLzXcVbNmQwErTyUiOp" + " y")[1] == 1   # mixed-case letters: a secret
    assert redact.redact("token " + "tk_" + "a1" * 14 + "b")[0].count("REDACTED") == 1


def test_time_window_clamps_to_replay_clock():
    as_of = dt.datetime(2026, 11, 15, 23, 0, tzinfo=UTC)
    s, e = timeutil.window("-2h", "2026-11-16T05:00:00Z", as_of, dt.timedelta(hours=1))
    assert e == as_of and s == dt.datetime(2026, 11, 15, 21, 0, tzinfo=UTC)
    s, e = timeutil.window("-30d", None, None, dt.timedelta(hours=1))
    assert e - s == timeutil.MAX_RANGE


def test_host_command_validation():
    assert hosts.validate("journal k3s -2h") == ["journal", "k3s", "-2h"]
    for bad in ("rm -rf /", "status ssh; id", "journal ssh $(id)", "env", "cat /etc/shadow", "", "container-logs x --follow"):
        with pytest.raises(ValueError):
            hosts.validate(bad)


def test_playbook_fills_placeholders_and_drops_empty():
    steps, rq = steps_for("container_restart", {"namespace": "edge", "name": "edge-caddy-x", "alertname": "X"}, "dgx-1")
    tools = [s["tool"] for s in steps]
    assert tools[:4] == ["promql", "promql", "promql", "changes"] and "k8s" in tools
    steps, _ = steps_for("argocd", {"alertname": "ArgoCDAppOutOfSync"}, "")
    assert all(s["args"].get("app", "x") for s in steps)  # no app name -> those steps dropped


def test_self_check_drops_uncited_claims():
    rca = {"confidence": "high", "claims": [{"claim": "a", "evidence": ["E1"]}, {"claim": "b", "evidence": ["E99"]},
                                             {"claim": "c", "evidence": []}]}
    out = self_check(rca, {"E1", "E2"})
    assert [c["claim"] for c in out["claims"]] == ["a"] and len(out["uncited"]) == 2
    assert "Removed" in to_markdown(out, "own-loop")
    loose = self_check({"claims": [{"claim": "x", "evidence": "E2, E7"}, "y per E1"]}, {"E1", "E2"})
    assert [c["evidence"] for c in loose["claims"]] == [["E2"], ["E1"]]


def test_formatters():
    prom = json.dumps({"data": [{"metric": {"__name__": "up", "job": "x"}, "values": [[1794781800, "1"], [1794782100, "0"]]}],
                       "exploreUrl": "https://grafana.nghodki.ai/explore?x"})
    text, link = _fmt_prom(prom, ranged=True)
    assert "min=0 max=1 last=0" in text and link.startswith("https://grafana")
    logs = json.dumps({"data": [{"timestamp": str(1794781800 * 10**9), "labels": {"host_name": "spark-83dc"},
                                 "line": json.dumps({"MESSAGE": "Out of memory: Killed process 1", "SYSLOG_IDENTIFIER": "kernel"})}] * 3})
    text, _ = _fmt_logs(logs)
    assert "x3 dgx-1" in text and "kernel: Out of memory" in text
