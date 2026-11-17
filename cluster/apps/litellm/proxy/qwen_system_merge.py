"""Merge mid-turn system messages for Qwen chat template compatibility.

Thinking mode stays ON (the model needs it for coherent output).
Reasoning tokens are stripped from the response so clients only see content.

DefenseClaw's plugin LLM judge replies are repaired after the call (repair_judge_reply, below): only for the judge
keys and only for the plugin analyzer's own prompt. A reply that can't be repaired with certainty is left as it was,
so DefenseClaw still fails closed on it.

File attachments become text: vLLM accepts no file parts ("Unsupported chat content part type: 'input_file'"), and
Claude Code sends a PDF it reads as an Anthropic `document` block inside a tool_result. Text documents pass through
as text, PDFs as their extracted text (pypdf, in the LiteLLM image); anything else becomes a short note to the model.
"""

import base64
import binascii
import io
import json
import logging
import re

from litellm.integrations.custom_logger import CustomLogger

# About 40k tokens: room for the rest of a coding agent's context in qwen3.8-27b's window.
MAX_DOCUMENT_CHARS = 160_000


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


def _pdf_text(raw):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"[page {number}]\n{text}")
    return "\n\n".join(pages), len(reader.pages)


def _note(name, why):
    return {"type": "text", "text": f"[Attached file {name}: {why}]"}


def _as_text(name, text, pages=None):
    if len(text) > MAX_DOCUMENT_CHARS:
        text = text[:MAX_DOCUMENT_CHARS] + f"\n[... truncated at {MAX_DOCUMENT_CHARS} characters]"
    where = f", {pages} pages" if pages else ""
    return {"type": "text", "text": f"<document name={name!r}{where}>\n{text}\n</document>"}


def _from_bytes(name, media_type, data):
    """A base64 file (Anthropic base64 source, OpenAI file_data) as one text part."""
    if isinstance(data, str) and data.startswith("data:") and "," in data:
        header, data = data.split(",", 1)
        media_type = media_type or header[5:].split(";", 1)[0]
    try:
        raw = base64.b64decode(data or "", validate=False)
    except (binascii.Error, ValueError):
        return _note(name, "not valid base64, not shown to the model")
    if media_type == "application/pdf" or raw[:5] == b"%PDF-":
        try:
            text, pages = _pdf_text(raw)
        except Exception as error:  # a broken PDF must not fail the whole request
            return _note(name, f"PDF could not be read ({type(error).__name__})")
        if not text.strip():
            return _note(name, f"PDF with {pages} pages and no text layer (scanned?); this model can't read it")
        return _as_text(name, text, pages)
    if (media_type or "").startswith("text/") or media_type in ("application/json", "application/xml"):
        return _as_text(name, raw.decode("utf-8", "replace"))
    return _note(name, f"{media_type or 'unknown type'} is not supported by this model")


def _convert_part(part):
    """One content part: file parts become text parts; tool_result content is converted inside."""
    if not isinstance(part, dict):
        return part
    kind = part.get("type")
    if kind == "document":  # Anthropic
        source = part.get("source") or {}
        name = part.get("title") or "document"
        stype = source.get("type")
        if stype == "text":
            return _as_text(name, source.get("data") or "")
        if stype == "content":
            return _as_text(name, _text(source.get("content")))
        if stype == "base64":
            return _from_bytes(name, source.get("media_type"), source.get("data"))
        return _note(name, f"a {stype or 'unknown'} reference, which this model can't fetch")
    if kind == "file":  # OpenAI chat completions
        file = part.get("file") or {}
        name = file.get("filename") or "file"
        if file.get("file_data"):
            return _from_bytes(name, None, file["file_data"])
        return _note(name, "an uploaded file id, which this model can't fetch")
    if kind == "input_file":  # OpenAI responses
        name = part.get("filename") or "file"
        if part.get("file_data"):
            return _from_bytes(name, None, part["file_data"])
        return _note(name, "a file reference, which this model can't fetch")
    if kind == "tool_result" and isinstance(part.get("content"), list):
        return {**part, "content": [_convert_part(p) for p in part["content"]]}
    return part


def documents_to_text(data):
    if not isinstance(data, dict):
        return data
    for key in ("messages", "input"):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for msg in items:
            if isinstance(msg, dict) and isinstance(msg.get("content"), list):
                msg["content"] = [_convert_part(p) for p in msg["content"]]
    return data


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


# --- DefenseClaw plugin judge replies ------------------------------------------------------------------------------
#
# DefenseClaw 1.0.9's plugin LLM analyzer (defenseclaw/scanner/plugin_scanner/llm_analyzer.py) asks for "ONLY the JSON
# array" of findings and parses the reply with json.loads after stripping one leading ``` fence. Anything that isn't a
# list there (a single finding object, {"findings": [...]}, prose before the array) becomes LLM-SCAN-ERROR, "the LLM
# judge did not run", and the plugin watcher quarantines the plugin (fail closed). qwen3.8-27b answers that way in
# about 8% of calls. The repair below rewrites only replies whose meaning is certain:
#
# - <think>...</think> and ``` fences are removed; the answer must be the last thing in the reply;
# - a single finding object becomes a one-item array; {"findings": [...]} (that key alone) becomes the array;
# - prose before a non-empty array is dropped (findings can only add severity, never clear a plugin).
#
# It never invents findings and never turns doubtful output into []: an empty array counts only when it is the whole
# answer (bare, fenced or as {"findings": []}), not after prose ("let me flag the subprocess call ... []" happened).
# Truncated replies (finish_reason "length"), broken JSON, {"error": ...}, other prompts (the meta-analyzer and the
# skill scanner want an object) and other keys are left exactly as they are.

log = logging.getLogger("qwen_system_merge")

JUDGE_KEY_ALIASES = frozenset({"defenseclaw-jetson-judge", "defenseclaw-dgx1"})
# Both must be in the system prompt: the plugin analyzer's, not the meta-analyzer's ("security meta-analyzer",
# "JSON object") nor the skill scanner's.
PLUGIN_JUDGE_MARKERS = ("You are a security analyzer for OpenClaw plugins", "Respond ONLY with the JSON array")
SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"})
WRAPPER_KEYS = frozenset({"findings", "results", "issues", "threats", "vulnerabilities"})

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"```[A-Za-z]*")
_DECODER = json.JSONDecoder()


def defenseclaw_parses(content):
    """True if DefenseClaw 1.0.9's _parse_llm_findings reads this reply as an array (its exact stripping)."""
    text = content.strip()
    if text.startswith("```"):
        text = text.lstrip("`").lstrip("json").lstrip("\n")
        if text.endswith("```"):
            text = text[:-3].rstrip("\n")
    try:
        return isinstance(json.loads(text), list)
    except (json.JSONDecodeError, ValueError):
        return False


def _is_finding(value):
    """A finding as the prompt describes it: a known severity and a rule id or title (other fields are optional)."""
    return (isinstance(value, dict) and str(value.get("severity", "")).strip().upper() in SEVERITIES
            and bool(value.get("rule_id") or value.get("title")))


def _as_findings(value):
    """The findings list a JSON value stands for, or None if it isn't unambiguously one."""
    if isinstance(value, list):
        return value if all(_is_finding(item) for item in value) else None
    if _is_finding(value):
        return [value]
    if isinstance(value, dict) and len(value) == 1:
        (key, inner), = value.items()
        if key.lower() in WRAPPER_KEYS and isinstance(inner, list) and all(_is_finding(i) for i in inner):
            return inner
    return None


def repair_judge_reply(content):
    """(repaired text, what was done) for a plugin judge reply DefenseClaw can't read, else (None, reason)."""
    if not isinstance(content, str) or not content.strip():
        return None, "empty"
    if defenseclaw_parses(content):
        return None, "already an array"
    text = _THINK_BLOCK.sub("", content)
    if "</think>" in text.lower():  # the template opened <think> itself: the reasoning ends at the last close tag
        text = text[text.lower().rindex("</think>") + len("</think>"):]
    if "<think>" in text.lower():
        return None, "unterminated <think>"
    text = text.strip()
    if text.endswith("```"):
        text = text[:-3].rstrip()
    found = []  # (start, end, findings) of every findings-shaped JSON value in the reply
    for match in re.finditer(r"[\[{]", text):
        start = match.start()
        if any(s <= start < e for s, e, _ in found):
            continue
        try:
            value, end = _DECODER.raw_decode(text, start)
        except (json.JSONDecodeError, ValueError):
            continue
        findings = _as_findings(value)
        if findings is not None:
            found.append((start, end, findings))
    if len(found) != 1:
        return None, "no findings JSON" if not found else "more than one findings JSON"
    start, end, findings = found[0]
    if text[end:].strip():
        return None, "text after the JSON"
    prose = bool(_FENCE.sub("", text[:start]).strip())  # anything before the JSON other than a ``` fence
    if prose and not findings:
        return None, "empty array after prose"
    kinds = []
    if content.strip() != text:
        kinds.append("stripped")
    if prose:
        kinds.append("prose dropped")
    value_text = text[start:end]
    if not value_text.startswith("["):
        kinds.append("object to array")
    return json.dumps(findings, ensure_ascii=False, indent=2), ", ".join(kinds) or "normalised"


def _system_text(data):
    parts = [_text(data.get("system"))] if isinstance(data, dict) and data.get("system") else []
    for msg in (data.get("messages") or []) if isinstance(data, dict) else []:
        if isinstance(msg, dict) and msg.get("role") == "system":
            parts.append(_text(msg.get("content")))
    return "\n".join(parts)


def is_plugin_judge_call(data, key_alias):
    if key_alias not in JUDGE_KEY_ALIASES:
        return False
    system = _system_text(data)
    return all(marker in system for marker in PLUGIN_JUDGE_MARKERS)


def repair_judge_response(data, key_alias, response):
    """Repair the choices of a DefenseClaw plugin judge response in place; returns what was done per choice."""
    if not is_plugin_judge_call(data, key_alias):
        return []
    done = []
    for choice in getattr(response, "choices", None) or []:
        if getattr(choice, "finish_reason", None) == "length":
            done.append("left: truncated")
            continue
        message = getattr(choice, "message", None)
        fixed, what = repair_judge_reply(getattr(message, "content", None))
        if fixed is None:
            done.append("left: " + what)
        else:
            message.content = fixed
            done.append("repaired: " + what)
    return done


class QwenSystemMerge(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        return merge_system(documents_to_text(data))

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        # DefenseClaw calls without streaming (litellm.completion), so only this hook is needed. A failure here must
        # never break the call: the response then goes out unchanged.
        try:
            alias = getattr(user_api_key_dict, "key_alias", None)
            for what in repair_judge_response(data, alias, response):
                if what != "left: already an array":
                    log.info("DefenseClaw judge reply (%s): %s", alias, what)
        except Exception as error:  # noqa: BLE001
            log.warning("DefenseClaw judge reply repair skipped: %s", type(error).__name__)
        return response

    def log_pre_api_call(self, model, messages, kwargs):
        merge_system(kwargs)


proxy_handler_instance = QwenSystemMerge()
