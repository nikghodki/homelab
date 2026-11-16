import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("exporter", Path(__file__).parents[1] / "litellm-usage-exporter.py")
ex = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ex)


def row(rid, alias="defenseclaw-jetson-judge", hash8="f38ff67b", model="qwen3.8-27b", status="success",
        ptok=100, ctok=20, dur_ms=1500, span_ms=1600, ip="10.42.2.0"):
    return (rid, alias, hash8, model, status, ptok, ctok, dur_ms, span_ms, ip)


def test_first_poll_only_primes_then_new_rows_count_once():
    u = ex.Usage()
    assert u.add_rows([row("a"), row("b")], now=0) == 0
    assert u.requests == {}
    assert u.add_rows([row("a"), row("b"), row("c"), row("d", status="failure", ptok=0, ctok=0)], now=1) == 2
    assert u.add_rows([row("c"), row("d")], now=2) == 0
    assert u.requests == {("defenseclaw-jetson-judge", "f38ff67b", "qwen3.8-27b", "success", "jetson"): 1,
                          ("defenseclaw-jetson-judge", "f38ff67b", "qwen3.8-27b", "failure", "jetson"): 1}
    assert u.tokens == {("defenseclaw-jetson-judge", "qwen3.8-27b", "prompt"): 100,
                        ("defenseclaw-jetson-judge", "qwen3.8-27b", "completion"): 20}


def test_histogram_only_successes_and_falls_back_to_the_time_span():
    u = ex.Usage()
    u.add_rows([], now=0)
    u.add_rows([row("a", dur_ms=None, span_ms=3000), row("b", status="failure", dur_ms=10)], now=1)
    h = u.hist["qwen3.8-27b"]
    assert h[ex.BUCKETS.index(2.5)] == 0 and h[ex.BUCKETS.index(5)] == 1
    assert h[len(ex.BUCKETS)] == 1 and h[-1] == 3.0


def test_callers_without_alias_or_key():
    assert ex.who(None, "5df01234") == "key:5df01234"
    assert ex.who(None, None) == "(no key)"
    assert ex.who("", "") == "(no key)"
    assert ex.who(None, "nonhash") == "(not a virtual key)"


def test_seen_ids_are_forgotten_after_the_window():
    u = ex.Usage()
    u.add_rows([row("a")], now=0)
    u.add_rows([], now=2 * ex.LOOKBACK_S + 1)
    assert "a" not in u.seen


def test_render_never_contains_more_than_hash8_and_escapes_labels():
    u = ex.Usage()
    u.add_rows([], now=0)
    u.add_rows([row("a", alias='we"ird')], now=1)
    u.set_snapshot([("hermes", "f879767a"), (None, "5df01234"), ("x", None)],
                   [("hermes", "f879767a", "qwen3.8-27b", "success", "10.42.2.1", 3, 30, 5)])
    text = u.render()
    assert 'litellm_usage_key_info{key_alias="hermes",api_key_hash="f879767a"} 1' in text
    assert 'litellm_usage_key_info{key_alias="key:5df01234",api_key_hash="5df01234"} 1' in text
    assert 'key_alias="we\\"ird"' in text
    assert 'litellm_usage_last24h_requests{key_alias="hermes",model="qwen3.8-27b",status="success",src="jetson"} 3' in text
    assert 'litellm_usage_last24h_tokens{key_alias="hermes",kind="prompt"} 30' in text
    assert 'litellm_usage_request_duration_seconds_bucket{model="qwen3.8-27b",le="+Inf"} 1' in text


def test_sql_cuts_the_hash_and_reads_no_prompts():
    for sql in (ex.KEYS_SQL, ex.RECENT_SQL, ex.DAY_SQL):
        assert "messages" not in sql and "response" not in sql and "proxy_server_request" not in sql
    cut = {"token": "case when token ~ '^[0-9a-f]{64}$' then left(token, 8) when coalesce(token, '') <> '' then 'nonhash' end",
           "api_key": "case when api_key ~ '^[0-9a-f]{64}$' then left(api_key, 8) "
                      "when coalesce(api_key, '') <> '' then 'nonhash' end"}
    assert cut["token"] in ex.KEYS_SQL and ex.KEYS_SQL.replace(cut["token"], "").count("token") == 0
    for sql in (ex.RECENT_SQL, ex.DAY_SQL):
        assert cut["api_key"] in sql and sql.replace(cut["api_key"], "").count(" api_key") == 0


def test_source_names_the_calling_host():
    assert ex.source("10.42.1.0") == "dgx-1" and ex.source("10.42.0.1") == "dgx-2"
    assert ex.source("10.42.2.0") == "jetson" and ex.source("10.42.3.0") == "dell"
    assert ex.source("127.0.0.1") == ex.source("172.18.0.5") == "dgx-1 (local)"
    assert ex.source("172.32.0.1") == "172.32.0.1" and ex.source("192.168.86.49") == "192.168.86.49"
    assert ex.source(None) == "(unknown)"
