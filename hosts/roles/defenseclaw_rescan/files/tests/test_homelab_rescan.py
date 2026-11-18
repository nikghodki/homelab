"""Tests for the weekly rescan job (homelab-rescan.py): scan commands, JSON
parsing, summary shape and exit codes. The CLI is faked; no LLM is touched."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("homelab_rescan", Path(__file__).parents[1] / "homelab-rescan.py")
rescan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rescan)

SKILLS = [
    {"connector": "hermes", "target": "/s/a", "findings": []},
    {"connector": "hermes", "target": "/s/b", "findings": [{"severity": "LOW"}]},
    {"connector": "hermes", "target": "/s/c", "findings": [{"severity": "HIGH"}, {"severity": "CRITICAL"}]},
]
PLUGINS = [
    {"connector": "hermes", "results": [
        {"target": "/p/a", "findings": [{"severity": "MEDIUM"}]},
        {"target": "/p/b", "findings": [], "error": "scanner failed"},
    ]},
]
MCP = [
    {"connector": "hermes", "target": "http://localhost:8123", "findings": [], "error": "server returned an error"},
    {"connector": "hermes", "target": "stdio:picoclaw", "findings": [], "error": None},
]
DOCS = {"skills": SKILLS, "plugins": PLUGINS, "mcp": MCP}


def proc(doc, rc):
    class P:
        pass

    p = P()
    p.returncode = rc
    p.stdout = "not json" if doc is None else json.dumps(doc)
    p.stderr = "onnxruntime warning line"
    return p


@pytest.fixture
def scans(tmp_path, monkeypatch):
    """Fake the CLI: every scan subcommand answers with its canned doc."""
    monkeypatch.setattr(rescan, "EXE", tmp_path / "defenseclaw")
    (tmp_path / "defenseclaw").write_text("#!/bin/sh\n")
    rc = {"skill": 0, "plugin": 0, "mcp": 1}  # mcp exits 1 (blocked/errored server)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        name = {"skill": "skills", "plugin": "plugins", "mcp": "mcp"}[cmd[1]]
        return proc(DOCS[name], rc[cmd[1]])

    monkeypatch.setattr(rescan.subprocess, "run", fake_run)
    return calls


def last_line(capsys):
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert out.startswith("homelab-rescan ")
    return json.loads(out.split("homelab-rescan ", 1)[1])


def test_scan_commands_use_llm_and_json(scans):
    rescan.main()
    assert [c[1:4] for c in scans] == [
        ["skill", "scan", "--all"], ["plugin", "scan", "--all"], ["mcp", "scan", "--all"],
    ]
    assert all("--json" in c for c in scans)
    assert "--use-llm" in scans[0] and "--use-llm" in scans[1]
    # MCP mirrors the watch scope: no --allow-private (the watch's mcp-scanner
    # refuses loopback/private URLs by default) and no LLM flag (mcp has none).
    assert "--allow-private" not in scans[2] and "--use-llm" not in scans[2]


def test_summary_counts_per_category(scans, capsys):
    assert rescan.main() == 1  # mcp exited 1 (errors on a target are not a job failure)
    s = last_line(capsys)
    assert s["skills"] == {"targets": 3, "findings": 3, "severe_findings": 2, "errors": 0, "duration_s": 0}
    assert s["plugins"] == {"targets": 2, "findings": 1, "severe_findings": 0, "errors": 1, "duration_s": 0}
    assert s["mcp"] == {"targets": 2, "findings": 0, "severe_findings": 0, "errors": 1, "duration_s": 0}


def test_non_json_output_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rescan, "EXE", tmp_path / "defenseclaw")
    (tmp_path / "defenseclaw").write_text("#!/bin/sh\n")
    monkeypatch.setattr(rescan.subprocess, "run", lambda cmd, **kw: proc(None, 1))
    assert rescan.main() == 1
    s = last_line(capsys)
    assert all("error" in s[cat] for cat in ("skills", "plugins", "mcp"))


def test_hard_failure_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rescan, "EXE", tmp_path / "defenseclaw")
    (tmp_path / "defenseclaw").write_text("#!/bin/sh\n")

    def boom(cmd, **kw):
        raise rescan.subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(rescan.subprocess, "run", boom)
    assert rescan.main() == 2
    s = last_line(capsys)
    assert "error" in s["skills"]


def test_missing_cli_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rescan, "EXE", tmp_path / "no-such-cli")
    assert rescan.main() == 2
