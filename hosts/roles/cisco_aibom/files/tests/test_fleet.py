import datetime
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("fleet", Path(__file__).parents[1] / "cisco-aibom-fleet.py")
fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fleet)


def report(root, comps):
    return {"sources": {"s": {"source_path": root, "components": comps}}}


REPORTS = {
    "/code/a": report("/code/a", {"model": [{"name": "Qwen/Qwen3-8B", "file_path": "/code/a/cfg.py"}],
                                  "secret": [{"name": "OPENAI_API_KEY=sk-123", "file_path": "/code/a/.env"}]}),
    "img:1": report("/x", {"agent": [{"name": "litellm-router", "file_path": "/x/app.py"}]}),
}


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fleet, "image_of", lambda c: "img:1")
    monkeypatch.setattr(fleet, "scan", lambda exe, source, is_image, timeout, work: json.loads(json.dumps(REPORTS[source])))
    monkeypatch.setattr(fleet.os.path, "isdir", lambda p: p in REPORTS)
    cfg = tmp_path / "targets.json"
    cfg.write_text(json.dumps({"host": "h", "exe": "x", "state": str(tmp_path / "state"), "keep_days": 30,
                               "dirs": [{"name": "a", "path": "/code/a"}], "containers": ["litellm"]}))

    def go():
        monkeypatch.setattr(fleet.sys, "argv", ["x", str(cfg)])
        rc = fleet.main()
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        return rc, lines
    return go, tmp_path / "state"


def test_first_run(run):
    go, state = run
    rc, lines = go()
    assert rc == 0
    (summary,) = lines
    assert summary["event"] == "aibom" and summary["first_run"] is True
    assert summary["total"] == 3 and summary["counts"] == {"agent": 1, "model": 1, "secret": 1}
    assert summary["targets"] == {"a": 2, "container:litellm": 1}
    assert len(list(state.glob("h-*.json"))) == 1


def test_diff_against_previous_run_and_secret_names_hidden(run):
    go, state = run
    go()
    today = next(state.glob("h-*.json"))
    yesterday = state / f"h-{(datetime.date.today() - datetime.timedelta(days=1)).isoformat()}.json"
    today.rename(yesterday)
    REPORTS["/code/a"]["sources"]["s"]["components"]["secret"].append({"name": "HF_TOKEN=hf_abc", "file_path": "/code/a/x"})
    try:
        rc, lines = go()
    finally:
        REPORTS["/code/a"]["sources"]["s"]["components"]["secret"].pop()
    summary, new = lines
    assert summary["added"] == 1 and summary["removed"] == 0 and summary["compared_to"] == yesterday.name
    assert new["event"] == "aibom.new" and new["type"] == "secret" and new["name"] == "(secret)"
    assert "hf_abc" not in json.dumps(lines)


def test_failed_target_is_an_error_not_a_removal(run, monkeypatch):
    go, state = run
    go()
    today = next(state.glob("h-*.json"))
    today.rename(state / f"h-{(datetime.date.today() - datetime.timedelta(days=1)).isoformat()}.json")

    def boom(c):
        raise RuntimeError("container litellm not found")
    monkeypatch.setattr(fleet, "image_of", boom)
    rc, lines = go()
    assert rc == 1
    assert lines[0]["removed"] == 0 and lines[0]["errors"]


def test_retention(run):
    go, state = run
    state.mkdir(parents=True)
    old = state / f"h-{(datetime.date.today() - datetime.timedelta(days=40)).isoformat()}.json"
    old.write_text(json.dumps({"targets": {}}))
    go()
    assert not old.exists()


def test_image_falls_back_to_copied_app_dirs(run, monkeypatch):
    go, state = run
    calls = []

    def scan(exe, source, is_image, timeout, work):
        calls.append((source, is_image))
        if is_image:
            raise RuntimeError('docker discovery failed: "blobs/sha256/x not found"')
        return json.loads(json.dumps(REPORTS["img:1"] if "image-app" in source else REPORTS[source]))
    monkeypatch.setattr(fleet, "scan", scan)
    monkeypatch.setattr(fleet, "copy_app_dirs", lambda image, dest: ["/app"])
    rc, lines = go()
    assert rc == 0 and lines[0]["targets"] == {"a": 2, "container:litellm": 1}
    doc = json.loads(next(state.glob("h-*.json")).read_text())
    assert doc["targets"]["container:litellm"]["method"] == "docker-cp-fallback"
    assert ("img:1", True) in calls
