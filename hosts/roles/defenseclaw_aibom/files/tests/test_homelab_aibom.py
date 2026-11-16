import datetime
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("homelab_aibom", Path(__file__).parents[1] / "homelab-aibom.py")
aibom = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aibom)


@pytest.fixture
def scan(tmp_path, monkeypatch):
    """Point the job at a temp state dir and a fake `defenseclaw aibom scan`; returns a setter for its output."""
    monkeypatch.setattr(aibom, "STATE", tmp_path)
    monkeypatch.setattr(aibom.sys, "argv", ["homelab-aibom", "30"])
    out = {}
    monkeypatch.setattr(aibom.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(out["doc"]), ""))
    return lambda doc: out.update(doc=doc)


def summary(capsys):
    line = capsys.readouterr().out.strip().splitlines()[-1]
    return json.loads(line.split(" ", 1)[1])


def test_same_day_rerun_compares_with_the_previous_day(tmp_path, scan, capsys):
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    (tmp_path / f"aibom-{yesterday}.json").write_text(json.dumps({"skills": ["a"]}))
    scan({"skills": ["a", "b"]})
    assert aibom.main() == 0
    assert summary(capsys)["added"] == {"skills": ["b"]}
    scan({"skills": ["a", "b", "c"]})
    assert aibom.main() == 0
    second = summary(capsys)
    assert second["changed"] is True and second["added"] == {"skills": ["b", "c"]}


def test_first_run_has_nothing_to_compare(scan, capsys):
    scan({"skills": ["a"]})
    assert aibom.main() == 0
    assert summary(capsys)["changed"] is None


def test_keeps_only_the_newest_files(tmp_path, scan, monkeypatch, capsys):
    for day in range(1, 6):
        (tmp_path / f"aibom-2026-01-0{day}.json").write_text("{}")
    monkeypatch.setattr(aibom.sys, "argv", ["homelab-aibom", "3"])
    scan({})
    aibom.main()
    assert len(list(tmp_path.glob("aibom-*.json"))) == 3
