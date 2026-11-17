"""Tests for the Ask Me overlay patch (patch_branding.py). Fixtures copy the v0.13.3 lines the patch touches."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import patch_branding as pb  # noqa: E402

ENV_V0133 = """# LICENSE covers this Open WebUI branding surface, including this name
# and any visual, textual, or symbolic identifiers it preserves.
# Do not alter, remove, obscure, or replace it except as LICENSE permits:
# https://docs.openwebui.com/license.
WEBUI_NAME = os.getenv('WEBUI_NAME', 'Open WebUI')
if WEBUI_NAME != 'Open WebUI':
    WEBUI_NAME += ' (Open WebUI)'

WEBUI_FAVICON_URL = 'https://openwebui.com/favicon.png'
"""
INDEX_V0133 = """<!doctype html>
<html lang="en">
	<head>
		<!-- LICENSE covers this Open WebUI branding surface, including name, logo, -->
		<title>Open WebUI</title>
	</head>
</html>
"""


def test_env_suffix_removed_license_comment_kept():
    out = pb.patch_env(ENV_V0133)
    assert "(Open WebUI)" not in out.replace('no " (Open WebUI)" suffix', "")
    assert "WEBUI_NAME += " not in out
    assert "# LICENSE covers this Open WebUI branding surface" in out
    assert "WEBUI_NAME = os.getenv('WEBUI_NAME', 'Open WebUI')" in out
    assert "WEBUI_FAVICON_URL = 'https://openwebui.com/favicon.png'" in out


def test_env_patched_code_gives_plain_name():
    ns = {"os": type("os", (), {"getenv": staticmethod(lambda k, d=None: "Ask Me")})}
    exec(pb.patch_env(ENV_V0133), ns)  # noqa: S102 - the fixture above, not upstream code
    assert ns["WEBUI_NAME"] == "Ask Me"


def test_env_changed_upstream_fails_clearly():
    changed = ENV_V0133.replace("    WEBUI_NAME += ' (Open WebUI)'", "    WEBUI_NAME = f'{WEBUI_NAME} (Open WebUI)'")
    with pytest.raises(pb.PatchError, match="found it 0 times"):
        pb.patch_env(changed)


def test_env_twice_is_reported_as_already_patched():
    with pytest.raises(pb.PatchError, match="already patched"):
        pb.patch_env(pb.patch_env(ENV_V0133))


def test_env_second_suffix_elsewhere_fails():
    extra = ENV_V0133 + "NAME2 = WEBUI_NAME + ' (Open WebUI)'\n"
    with pytest.raises(pb.PatchError, match="still there"):
        pb.patch_env(extra)


def test_index_title():
    out = pb.patch_index(INDEX_V0133, "Ask Me")
    assert "<title>Ask Me</title>" in out
    assert "<!-- LICENSE covers this Open WebUI branding surface" in out


def test_index_missing_title_fails():
    with pytest.raises(pb.PatchError, match="found it 0 times"):
        pb.patch_index(INDEX_V0133.replace("Open WebUI</title>", "WebUI</title>"), "Ask Me")


@pytest.mark.parametrize("bad", ["", "<b>x</b>", "A & B"])
def test_index_title_must_be_plain(bad):
    with pytest.raises(pb.PatchError, match="plain text"):
        pb.patch_index(INDEX_V0133, bad)


def test_run_and_check(tmp_path, capsys):
    (tmp_path / "backend/open_webui").mkdir(parents=True)
    (tmp_path / "build").mkdir()
    (tmp_path / pb.ENV_FILE).write_text(ENV_V0133)
    (tmp_path / pb.INDEX_FILE).write_text(INDEX_V0133)
    assert pb.main(["--root", str(tmp_path), "--check"]) == 0
    assert (tmp_path / pb.ENV_FILE).read_text() == ENV_V0133  # --check writes nothing
    assert pb.main(["--root", str(tmp_path)]) == 0
    assert "<title>Ask Me</title>" in (tmp_path / pb.INDEX_FILE).read_text()
    assert pb.main(["--root", str(tmp_path)]) == 1
    assert "no longer applies" in capsys.readouterr().err


def test_missing_file(tmp_path):
    assert pb.main(["--root", str(tmp_path)]) == 1
