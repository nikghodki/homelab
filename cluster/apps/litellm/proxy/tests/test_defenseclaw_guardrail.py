import asyncio
import json

import httpx
import pytest

import defenseclaw_guardrail as dg


def make(handler, **kw):
    g = dg.DefenseClawGuardrail(api_base="http://dc:18970", api_key="tok", **kw)
    g._transport = httpx.MockTransport(handler)
    return g


def run(coro):
    return asyncio.run(coro)


class Key:
    key_alias = "picoclaw-pi"
    token = "hashed"


def test_mcp_tool_call_is_sent_as_pre_tool_and_block_raises():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx.Response(200, json={"action": "block", "reason": "robot.move outside daytime", "rule_ids": ["R1"]})

    g = make(handler)
    data = {"name": "robot_move", "arguments": {"to": "kitchen"}, "litellm_call_id": "c1"}
    with pytest.raises(dg.GuardrailBlocked) as e:
        run(g.async_pre_call_hook(Key(), None, data, "call_mcp_tool"))
    b = seen["body"]
    assert b["event"] == "pre_tool" and b["tool"] == {"name": "robot_move", "kind": "mcp", "input": {"to": "kitchen"}}
    assert b["tool_use_id"] == "c1" and b["session_id"].startswith("litellm:picoclaw-pi")
    assert seen["headers"]["authorization"] == "Bearer tok" and seen["headers"]["x-defenseclaw-client"] == "litellm"
    assert "robot.move outside daytime" in str(e.value) and "R1" in str(e.value)


def test_chat_prompt_is_sent_as_user_prompt_and_allow_passes():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"action": "allow"})

    g = make(handler)
    data = {"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "hello there"}],
            "litellm_session_id": "s9"}
    assert run(g.async_pre_call_hook(Key(), None, data, "acompletion")) is data
    assert seen["body"] == {"event": "user_prompt", "session_id": "litellm:picoclaw-pi:s9", "prompt": "hello there"}


def test_alert_is_allowed():
    g = make(lambda r: httpx.Response(200, json={"action": "alert", "reason": "odd"}))
    data = {"name": "web_search", "arguments": {}}
    assert run(g.async_pre_call_hook(Key(), None, data, "call_mcp_tool")) is data


def test_tool_call_fails_closed_when_defenseclaw_is_down():
    def handler(request):
        raise httpx.ConnectError("down")

    g = make(handler)
    with pytest.raises(dg.GuardrailBlocked) as e:
        run(g.async_pre_call_hook(Key(), None, {"name": "ha_unlock", "arguments": {}}, "call_mcp_tool"))
    assert "unreachable" in str(e.value)


def test_prompt_fails_open_when_defenseclaw_is_down():
    g = make(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))
    data = {"messages": [{"role": "user", "content": "hi"}]}
    assert run(g.async_pre_call_hook(Key(), None, data, "acompletion")) is data


def test_bad_answer_fails_closed_for_tools():
    g = make(lambda r: httpx.Response(500, text="oops"))
    with pytest.raises(dg.GuardrailBlocked):
        run(g.async_pre_call_hook(Key(), None, {"name": "x", "arguments": {}}, "call_mcp_tool"))


@pytest.mark.parametrize("body", [None, [], "allow", 1])
def test_non_object_answer_is_no_verdict(body):
    # JSON that isn't an object must take the no-verdict path: open for prompts, closed for tools
    g = make(lambda r: httpx.Response(200, json=body))
    data = {"messages": [{"role": "user", "content": "hi"}]}
    assert run(g.async_pre_call_hook(Key(), None, data, "acompletion")) is data
    with pytest.raises(dg.GuardrailBlocked):
        run(g.async_pre_call_hook(Key(), None, {"name": "x", "arguments": {}}, "call_mcp_tool"))


def test_multimodal_user_content_is_flattened():
    seen = {}
    g = make(lambda r: (seen.setdefault("b", json.loads(r.content)), httpx.Response(200, json={"action": "allow"}))[1])
    data = {"messages": [{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "image_url", "image_url": {}},
                                                      {"type": "text", "text": "b"}]}]}
    run(g.async_pre_call_hook(Key(), None, data, "acompletion"))
    assert seen["b"]["prompt"] == "a\nb"


def test_other_call_types_are_not_checked():
    g = make(lambda r: pytest.fail("should not be called"))
    data = {"input": ["x"]}
    assert run(g.async_pre_call_hook(Key(), None, data, "aembedding")) is data


@pytest.mark.parametrize("skip", [["picoclaw-pi"], "judge-a, picoclaw-pi", "picoclaw-pi judge-b"])
def test_skipped_key_aliases_are_not_checked(skip):
    # the scanners' and judges' own keys: their prompts quote what they judge
    g = make(lambda r: pytest.fail("should not be called"), skip_key_aliases=skip)
    assert run(g.async_pre_call_hook(Key(), None, {"messages": [{"role": "user", "content": "hi"}]}, "acompletion"))
    assert run(g.async_pre_call_hook(Key(), None, {"name": "x", "arguments": {}}, "call_mcp_tool"))


def test_other_keys_are_still_checked_when_some_are_skipped():
    seen = []
    g = make(lambda r: (seen.append(1), httpx.Response(200, json={"action": "allow"}))[1], skip_key_aliases=["judge"])
    run(g.async_pre_call_hook(Key(), None, {"messages": [{"role": "user", "content": "hi"}]}, "acompletion"))
    assert seen == [1]
