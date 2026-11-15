import hashlib
import importlib.util
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location(
    "bundle", Path(__file__).parents[1] / "defenseclaw-bundle.py")
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)

RELEASES = {
    "1.0.0": {"dash/a.json": b"{}", "rules/alerts.yml": b"a: 1\n", "loki.yaml": b"retention: 24h\n"},
    "1.1.0": {"dash/a.json": b'{"v": 2}', "dash/b.json": b"{}", "rules/alerts.yml": b"a: 2\n",
              "loki.yaml": b"retention: 48h\n"},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "REPO", tmp_path)
    monkeypatch.setattr(bundle, "fetch_bundle", lambda version, root: RELEASES[version])
    (tmp_path / "dash").mkdir()
    (tmp_path / "dash/a.json").write_bytes(b"{}")
    (tmp_path / "alerts.yml").write_bytes(b"a: 1\n")
    (tmp_path / "loki.yaml").write_bytes(b"retention: 30d\n")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        'version: "1.0.0"\nadapted_base: "1.0.0"\nroot: x\n'
        "verbatim:\n  dash/: dash\n  rules/alerts.yml: alerts.yml\n"
        f"adapted:\n  loki.yaml:\n    dest: loki.yaml\n    upstream_sha256: {sha(RELEASES['1.0.0']['loki.yaml'])}\n")
    return tmp_path, manifest


def load(manifest):
    return yaml.safe_load(manifest.read_text())


def test_check_passes_on_pinned_release(repo):
    _, manifest = repo
    assert bundle.check(load(manifest), RELEASES["1.0.0"]) == []


def test_bump_fails_check(repo):
    _, manifest = repo
    m = load(manifest)
    problems = bundle.check(m, RELEASES["1.1.0"])
    assert any("dash/a.json: differs" in p for p in problems)
    assert any("dash/b.json: missing here" in p for p in problems)
    assert any("alerts.yml: differs" in p for p in problems)
    assert any("loki.yaml: upstream loki.yaml changed" in p for p in problems)


def test_sync_copies_verbatim_and_records_adapted(repo, capsys):
    root, manifest = repo
    manifest.write_text(manifest.read_text().replace('version: "1.0.0"', 'version: "1.1.0"'))
    bundle.sync(load(manifest), RELEASES["1.1.0"], manifest)
    m = load(manifest)
    assert (root / "dash/a.json").read_bytes() == b'{"v": 2}'
    assert (root / "dash/b.json").exists()
    assert (root / "loki.yaml").read_bytes() == b"retention: 30d\n"  # ported by hand, not overwritten
    assert m["adapted_base"] == "1.1.0"
    assert m["adapted"]["loki.yaml"]["upstream_sha256"] == sha(RELEASES["1.1.0"]["loki.yaml"])
    out = capsys.readouterr().out
    assert "-retention: 24h" in out and "+retention: 48h" in out
    assert bundle.check(m, RELEASES["1.1.0"]) == []


def test_stale_dashboard_is_reported(repo):
    root, manifest = repo
    (root / "dash/old.json").write_bytes(b"{}")
    assert any("dash/old.json: no longer upstream" in p for p in bundle.check(load(manifest), RELEASES["1.0.0"]))
