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
    monkeypatch.setattr(fleet, "copy_app_dirs", lambda image, dest, extra=(): ["/app"])
    rc, lines = go()
    assert rc == 0 and lines[0]["targets"] == {"a": 2, "container:litellm": 1}
    doc = json.loads(next(state.glob("h-*.json")).read_text())
    assert doc["targets"]["container:litellm"]["method"] == "docker-cp-fallback"
    assert ("img:1", True) in calls


def set_cfg(tmp_path, **extra):
    cfg = tmp_path / "targets.json"
    cfg.write_text(json.dumps({**json.loads(cfg.read_text()), **extra}))


def test_low_memory_skips_image_targets_only(run, tmp_path, monkeypatch):
    go, state = run
    set_cfg(tmp_path, image_min_mem_gib=20)
    monkeypatch.setattr(fleet, "mem_available_gib", lambda: 12.5)
    monkeypatch.setattr(fleet, "image_of", lambda c: pytest.fail("a skipped image must not be touched"))
    rc, lines = go()
    assert rc == 0  # a skip is not an error
    skip, summary = lines
    assert skip == {"event": "aibom.skipped", "host": "h", "target": "container:litellm",
                    "reason": "skipped: low memory", "mem_available_gib": 12.5, "need_gib": 20.0}
    assert summary["skipped"] == ["container:litellm"] and summary["errors"] == []
    assert summary["targets"] == {"a": 2}
    doc = json.loads(next(state.glob("h-*.json")).read_text())
    assert doc["targets"]["container:litellm"]["status"] == "skipped"


def test_per_container_threshold_and_enough_memory(run, tmp_path, monkeypatch):
    go, _ = run
    set_cfg(tmp_path, image_min_mem_gib=20, image_min_mem_gib_by_container={"litellm": 40})
    monkeypatch.setattr(fleet, "mem_available_gib", lambda: 41.0)
    rc, lines = go()
    assert rc == 0 and lines[0]["skipped"] == [] and lines[0]["targets"]["container:litellm"] == 1
    monkeypatch.setattr(fleet, "mem_available_gib", lambda: 39.0)
    rc, lines = go()
    assert lines[0]["event"] == "aibom.skipped" and lines[0]["need_gib"] == 40.0


def test_skipped_target_is_compared_with_its_last_real_scan(run, tmp_path, monkeypatch):
    go, state = run
    day = datetime.date.today()
    go()  # scanned: becomes "3 days ago"
    next(state.glob("h-*.json")).rename(state / f"h-{(day - datetime.timedelta(days=3)).isoformat()}.json")
    set_cfg(tmp_path, image_min_mem_gib=20)
    monkeypatch.setattr(fleet, "mem_available_gib", lambda: 5.0)
    rc, lines = go()  # skipped: becomes "yesterday"
    assert lines[1]["removed"] == 0 and lines[1]["added"] == 0
    (state / f"h-{day.isoformat()}.json").rename(state / f"h-{(day - datetime.timedelta(days=1)).isoformat()}.json")
    monkeypatch.setattr(fleet, "mem_available_gib", lambda: 64.0)
    rc, lines = go()  # scanned again: nothing new, although yesterday had no report for it
    (summary,) = lines
    assert summary["added"] == 0 and summary["removed"] == 0 and summary["skipped"] == []


def test_mem_available_reads_proc_meminfo():
    assert fleet.mem_available_gib() > 0


HA = "ghcr.io/home-assistant/home-assistant@sha256:" + "a" * 64


def remote_run(run, tmp_path, monkeypatch, **extra):
    """dgx-2-style config: its own container plus the Jetson's image by digest."""
    go, state = run
    set_cfg(tmp_path, remote_images=[{"host": "jetson", "name": "homeassistant", "image": HA,
                                      "paths": ["/usr/src/homeassistant"]}], **extra)
    REPORTS[HA] = report("/y", {"model": [{"name": "whisper", "file_path": "/y/stt.py"}]})
    docker_calls = []

    def docker(*args, timeout=600):
        docker_calls.append(args)
        if args[:2] == ("image", "inspect"):
            raise RuntimeError("no such image")
        return ""
    monkeypatch.setattr(fleet, "docker", docker)
    return go, state, docker_calls


def test_remote_image_is_logged_and_stored_as_the_other_host(run, tmp_path, monkeypatch):
    go, state, docker_calls = remote_run(run, tmp_path, monkeypatch)
    rc, lines = go()
    assert rc == 0
    own, remote = lines
    assert own["host"] == "h" and "scanned_on" not in own and "image:homeassistant" not in own["targets"]
    assert remote["host"] == "jetson" and remote["scanned_on"] == "h"
    assert remote["targets"] == {"image:homeassistant": 1}
    doc = json.loads(next(state.glob("jetson-*.json")).read_text())
    assert doc["scanned_on"] == "h" and doc["targets"]["image:homeassistant"]["image"] == HA
    assert ("pull", "--quiet", HA) in docker_calls
    assert json.loads((state / "remote-images.json").read_text()) == [HA]


def test_remote_image_respects_the_memory_guard(run, tmp_path, monkeypatch):
    go, state, docker_calls = remote_run(run, tmp_path, monkeypatch, image_min_mem_gib=20)
    monkeypatch.setattr(fleet, "mem_available_gib", lambda: 8.0)
    rc, lines = go()
    assert rc == 0
    skipped = [x for x in lines if x["event"] == "aibom.skipped"]
    assert {(x["host"], x["target"]) for x in skipped} == {("h", "container:litellm"), ("jetson", "image:homeassistant")}
    assert [x for x in skipped if x["host"] == "jetson"][0]["scanned_on"] == "h"
    assert not any(c[0] == "pull" for c in docker_calls)


def test_remote_image_must_be_pinned_by_digest(run, tmp_path, monkeypatch):
    go, state = run
    set_cfg(tmp_path, remote_images=[{"host": "jetson", "name": "ha", "image": "ghcr.io/home-assistant/home-assistant:stable"}])
    rc, lines = go()
    assert rc == 1 and "pinned by digest" in lines[-1]["errors"][0]


def test_remote_fallback_copies_the_extra_paths(run, tmp_path, monkeypatch):
    go, state, _ = remote_run(run, tmp_path, monkeypatch)
    seen = {}

    def scan(exe, source, is_image, timeout, work):
        if is_image:
            raise RuntimeError("docker discovery failed")
        return json.loads(json.dumps(REPORTS[HA] if "image-app" in source else REPORTS[source]))

    def copy(image, dest, extra=()):
        seen[image] = list(extra)
        return ["/config", *extra]
    monkeypatch.setattr(fleet, "scan", scan)
    monkeypatch.setattr(fleet, "copy_app_dirs", copy)
    rc, _ = go()
    assert rc == 0 and seen[HA] == ["/usr/src/homeassistant"]


def test_images_no_longer_configured_are_removed(run, tmp_path, monkeypatch):
    go, state, docker_calls = remote_run(run, tmp_path, monkeypatch)
    state.mkdir(parents=True)
    old = "ghcr.io/home-assistant/home-assistant@sha256:" + "b" * 64
    (state / "remote-images.json").write_text(json.dumps([old]))
    go()
    assert ("image", "rm", old) in docker_calls
    assert json.loads((state / "remote-images.json").read_text()) == [HA]
