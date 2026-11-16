"""Merge mid-turn system messages for Qwen chat template compatibility.

Thinking mode stays ON (the model needs it for coherent output).
Reasoning tokens are stripped from the response so clients only see content.

File attachments become text: vLLM accepts no file parts ("Unsupported chat content part type: 'input_file'"), and
Claude Code sends a PDF it reads as an Anthropic `document` block inside a tool_result. Text documents pass through
as text, PDFs as their extracted text (pypdf, in the LiteLLM image); anything else becomes a short note to the model.
"""

import base64
import binascii
import io

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


class QwenSystemMerge(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        return merge_system(documents_to_text(data))

    def log_pre_api_call(self, model, messages, kwargs):
        merge_system(kwargs)


proxy_handler_instance = QwenSystemMerge()
