"""DefenseClaw guardrail for LiteLLM (homelab plan P2.4).

Sends every chat prompt and every MCP tool call that goes through LiteLLM to DefenseClaw's agent-gateway route
(POST /api/v1/agent-gateway/hook) and enforces the answer: "block" stops the call, "allow" and "alert" let it run.

Fail modes follow the homelab design: an MCP tool call that gets no usable answer is refused (fail closed); a chat
prompt that gets no usable answer runs with a warning (fail open, visible in the logs).

LiteLLM config:
    guardrails:
      - guardrail_name: defenseclaw
        litellm_params:
          guardrail: defenseclaw_guardrail.DefenseClawGuardrail
          mode: [pre_call, pre_mcp_call]
          default_on: true
          api_base: os.environ/DEFENSECLAW_URL       # e.g. http://host.docker.internal:18970
          api_key: os.environ/DEFENSECLAW_TOKEN      # the gateway token
          skip_key_aliases: [defenseclaw-dgx1]       # optional, see below

Keys in ``skip_key_aliases`` are not checked: DefenseClaw's own LLM judge and the security scanners call models
through LiteLLM with prompts that quote the suspicious text they are judging, so checking them would block the
scanners (and the judge would recurse into itself). Only the LiteLLM admin can name a key's alias.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

try:  # inside LiteLLM
    from litellm.integrations.custom_guardrail import CustomGuardrail
except ImportError:  # unit tests run without LiteLLM
    class CustomGuardrail:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.guardrail_name = kwargs.get("guardrail_name", "defenseclaw")

log = logging.getLogger("defenseclaw_guardrail")

CHAT_CALL_TYPES = {"completion", "acompletion", "text_completion", "atext_completion", "responses", "aresponses",
                   "anthropic_messages"}
MCP_CALL_TYPES = {"call_mcp_tool", "mcp_call"}


try:  # inside LiteLLM: an HTTPException reaches the caller as 400 (any other exception would be a 500)
    from fastapi import HTTPException as _Refusal
except ImportError:  # unit tests run without FastAPI
    _Refusal = None


class GuardrailBlocked(_Refusal or Exception):  # type: ignore[misc]
    """Raised to stop a call. LiteLLM returns it to the caller as HTTP 400 with the reason."""

    def __init__(self, message: str) -> None:
        self.message = message
        if _Refusal is not None:
            super().__init__(status_code=400, detail={"error": message})
        else:
            super().__init__(message)

    def __str__(self) -> str:
        return self.message


def _last_user_text(messages: list[dict] | None) -> str:
    for m in reversed(messages or []):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


class DefenseClawGuardrail(CustomGuardrail):
    def __init__(self, api_base: str | None = None, api_key: str | None = None, timeout: float = 3.5,
                 client_name: str = "litellm", skip_key_aliases: list[str] | str | None = None,
                 **kwargs: Any) -> None:
        self.api_base = (api_base or "http://127.0.0.1:18970").rstrip("/")
        self.api_key = api_key
        self.timeout = float(timeout)
        self.client_name = client_name
        if isinstance(skip_key_aliases, str):
            skip_key_aliases = [a for a in skip_key_aliases.replace(",", " ").split() if a]
        self.skip_key_aliases = frozenset(skip_key_aliases or ())
        self._transport: httpx.AsyncBaseTransport | None = None  # tests inject a mock transport
        super().__init__(**kwargs)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _session(user_api_key_dict: Any, data: dict) -> str:
        who = getattr(user_api_key_dict, "key_alias", None) or getattr(user_api_key_dict, "token", None) or "unknown"
        sid = data.get("litellm_session_id") or (data.get("metadata") or {}).get("session_id") \
            or data.get("litellm_call_id") or "default"
        return f"litellm:{who}:{sid}"

    async def _ask(self, event: dict) -> dict:
        headers = {"Content-Type": "application/json", "X-DefenseClaw-Client": self.client_name}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            r = await client.post(f"{self.api_base}/api/v1/agent-gateway/hook", json=event, headers=headers)
        r.raise_for_status()
        answer = r.json()
        if not isinstance(answer, dict) or answer.get("action") not in ("allow", "alert", "block"):
            raise ValueError(f"no verdict in answer: {str(answer)[:200]}")
        return answer

    # ------------------------------------------------------------------ LiteLLM hook
    async def async_pre_call_hook(self, user_api_key_dict: Any, cache: Any, data: dict, call_type: str) -> dict:
        if getattr(user_api_key_dict, "key_alias", None) in self.skip_key_aliases:
            return data
        session = self._session(user_api_key_dict, data)
        if call_type in MCP_CALL_TYPES:
            event = {"event": "pre_tool", "session_id": session,
                     "tool_use_id": data.get("litellm_call_id") or data.get("id") or "unknown",
                     "tool": {"name": data.get("name", ""), "kind": "mcp", "input": data.get("arguments") or {}}}
            fail_closed = True
        elif call_type in CHAT_CALL_TYPES:
            prompt = _last_user_text(data.get("messages"))
            if not prompt:
                return data
            event = {"event": "user_prompt", "session_id": session, "prompt": prompt}
            fail_closed = False
        else:
            return data

        try:
            answer = await self._ask(event)
        except (httpx.HTTPError, ValueError) as exc:
            if fail_closed:
                raise GuardrailBlocked(f"DefenseClaw unreachable or gave no verdict ({type(exc).__name__}); "
                                       f"tool call '{event['tool']['name']}' refused") from None
            log.warning("DefenseClaw unreachable for a prompt (%s); allowing it", type(exc).__name__)
            return data

        if answer["action"] == "block":
            rules = ", ".join(answer.get("rule_ids") or [])
            raise GuardrailBlocked(f"Blocked by DefenseClaw: {answer.get('reason', 'policy')}"
                                   + (f" (rules: {rules})" if rules else ""))
        if answer["action"] == "alert":
            log.info("DefenseClaw alert for %s: %s", event["event"], answer.get("reason", ""))
        return data
