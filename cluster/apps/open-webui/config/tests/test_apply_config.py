"""Pure helpers of apply_config.py, plus settings.yaml itself (no Open WebUI needed)."""
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import apply_config as ac  # noqa: E402

SETTINGS = yaml.safe_load((HERE / "settings.yaml").read_text())


def test_access_grants():
    assert ac.access_grants("public", {}) == [{"principal_type": "user", "principal_id": "*", "permission": "read"}]
    assert ac.access_grants("private", {}) == []
    assert ac.access_grants({"groups": ["admins"]}, {"admins": "g1"}) == [
        {"principal_type": "group", "principal_id": "g1", "permission": "read"}]
    with pytest.raises(ValueError):
        ac.access_grants({"groups": ["family"]}, {"admins": "g1"})
    with pytest.raises(ValueError):
        ac.access_grants("everyone", {})


def test_connections_and_diff_never_show_keys():
    env = {"LITELLM_API_KEY": "sk-lite-secret", "HERMES_API_KEY": "hermes-secret"}
    urls, keys, configs = ac.desired_connections(SETTINGS["connections"], env)
    assert urls == ["http://10.43.0.150:4000/v1", "http://192.168.86.211:8642/v1"]
    assert keys == ["sk-lite-secret", "hermes-secret"]
    current = {"ENABLE_OPENAI_API": True, "OPENAI_API_BASE_URLS": ["http://10.43.0.150:4000/v1"],
               "OPENAI_API_KEYS": ["sk-lite-secret"], "OPENAI_API_CONFIGS": {}}
    diff = ac.connections_differ(current, urls, keys, configs)
    assert "OPENAI_API_BASE_URLS" in diff and "OPENAI_API_KEYS[1]" in diff
    assert not any("secret" in d for d in diff)
    same = {"ENABLE_OPENAI_API": True, "OPENAI_API_BASE_URLS": urls, "OPENAI_API_KEYS": keys,
            "OPENAI_API_CONFIGS": configs}
    assert ac.connections_differ(same, urls, keys, configs) == []
    stale = dict(same, OPENAI_API_BASE_URLS=["http://litellm-proxy:4000/v1", urls[1]])
    assert ac.connections_differ(stale, urls, keys, configs) == ["OPENAI_API_BASE_URLS"]


def test_missing_key_env_fails():
    with pytest.raises(ValueError, match="HERMES_API_KEY"):
        ac.desired_connections(SETTINGS["connections"], {"LITELLM_API_KEY": "x"})


def test_model_differs_and_form():
    spec = SETTINGS["models"][0]
    assert ac.model_differs(spec, None) == ["missing"]
    cur = {"id": spec["id"], "name": "qwen3.8-27b", "base_model_id": None, "is_active": True,
           "meta": {"description": None, "profile_image_url": "/static/x.png"}, "params": {"temperature": 0.2}}
    assert set(ac.model_differs(spec, cur)) == {"name", "description", "capabilities"}
    form = ac.model_form(spec, cur)
    assert form["meta"]["profile_image_url"] == "/static/x.png"  # kept
    assert form["params"] == {"temperature": 0.2}                # kept
    assert form["meta"]["capabilities"]["usage"] is True
    cur2 = dict(cur, name=spec["name"], meta=form["meta"])
    assert ac.model_differs(spec, cur2) == []


def test_settings_contract():
    """The safety-relevant parts of settings.yaml."""
    models = {m["id"]: m for m in SETTINGS["models"]}
    assert models["hermes.hermes-agent"]["access"] == {"groups": ["admins"]}
    assert models["qwen3.8-27b"]["access"] == "public"
    assert SETTINGS["default_models"] == "qwen3.8-27b"
    admins = [g for g in SETTINGS["groups"] if g["name"] == "admins"]
    assert admins and admins[0]["members"] == "admins"
    hermes = SETTINGS["connections"][1]
    assert hermes["config"]["prefix_id"] == "hermes" and hermes["config"]["model_ids"] == ["hermes-agent"]
    assert all(m["capabilities"]["usage"] for m in SETTINGS["models"])
    assert SETTINGS["api_keys"]["endpoint_restrictions"] is True
    assert "/api/v1/chats" not in SETTINGS["api_keys"]["allowed_endpoints"]  # the Job's key can't read chats
    tps = [f for f in SETTINGS["functions"] if f["id"] == "tps_meter"][0]
    assert tps["global"] and tps["active"] and (HERE.parent / "functions" / tps["file"]).is_file()
    assert "sk-" not in (HERE / "settings.yaml").read_text()  # keys are named by env var, never written here


def test_api_url_must_be_http():
    with pytest.raises(ac.ApiError):
        ac.Api("file:///etc/passwd", "sk-x")
    a = ac.Api("http://10.43.0.130:8080", "sk-x")
    assert (a.scheme, a.host, a.port, a.prefix) == ("http", "10.43.0.130", 8080, "")
