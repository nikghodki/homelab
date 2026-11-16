"""Merge mid-turn system messages for Qwen chat template compatibility.

Thinking mode stays ON (the model needs it for coherent output).
Reasoning tokens are stripped from the response so clients only see content.
"""

from litellm.integrations.custom_logger import CustomLogger


def _text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text") or "")
            else:
                parts.append(str(part))
        return "\n".join(p for p in parts if p)
    return str(content)


def merge_system(data):
    if not isinstance(data, dict):
        return data
    messages = data.get("messages")
    if not isinstance(messages, list):
        return data

    sys_parts = []
    rest = []

    top = data.get("system")
    if isinstance(top, str) and top.strip():
        sys_parts.append(top)
    elif isinstance(top, list):
        text = _text(top)
        if text.strip():
            sys_parts.append(text)

    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            text = _text(msg.get("content"))
            if text.strip():
                sys_parts.append(text)
        else:
            rest.append(msg)

    merged = "\n\n".join(sys_parts)
    if "system" in data:
        if merged:
            data["system"] = merged
        data["messages"] = rest
    elif merged:
        data["messages"] = [{"role": "system", "content": merged}] + rest
    else:
        data["messages"] = rest

    return data


class QwenSystemMerge(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        return merge_system(data)

    def log_pre_api_call(self, model, messages, kwargs):
        merge_system(kwargs)


proxy_handler_instance = QwenSystemMerge()
