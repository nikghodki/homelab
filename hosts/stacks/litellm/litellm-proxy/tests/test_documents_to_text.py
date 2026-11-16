import asyncio
import base64

import pytest

import qwen_system_merge as q


def b64(raw):
    return base64.b64encode(raw).decode()


def doc(source, title="notes.pdf"):
    return {"type": "document", "title": title, "source": source}


def texts(data, msg=0):
    return [p.get("text", "") for p in data["messages"][msg]["content"]]


def test_text_document_passes_as_text():
    data = {"messages": [{"role": "user", "content": [doc({"type": "text", "media_type": "text/plain", "data": "hello"})]}]}
    q.documents_to_text(data)
    part = data["messages"][0]["content"][0]
    assert part["type"] == "text" and "hello" in part["text"] and "notes.pdf" in part["text"]


def test_pdf_inside_tool_result_becomes_extracted_text(monkeypatch):
    monkeypatch.setattr(q, "_pdf_text", lambda raw: ("[page 1]\nquarterly plan", 1))
    pdf = doc({"type": "base64", "media_type": "application/pdf", "data": b64(b"%PDF-1.7 fake")})
    data = {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [pdf]}]}]}
    q.documents_to_text(data)
    inner = data["messages"][0]["content"][0]["content"][0]
    assert inner["type"] == "text" and "quarterly plan" in inner["text"] and "1 pages" in inner["text"]
    assert data["messages"][0]["content"][0]["tool_use_id"] == "t1"


def test_scanned_pdf_gets_a_note(monkeypatch):
    monkeypatch.setattr(q, "_pdf_text", lambda raw: ("", 3))
    data = {"messages": [{"role": "user", "content": [doc({"type": "base64", "media_type": "application/pdf", "data": b64(b"%PDF-")})]}]}
    q.documents_to_text(data)
    assert "no text layer" in texts(data)[0] and "3 pages" in texts(data)[0]


def test_broken_pdf_does_not_fail_the_request(monkeypatch):
    def boom(raw):
        raise ValueError("bad xref")

    monkeypatch.setattr(q, "_pdf_text", boom)
    data = {"messages": [{"role": "user", "content": [doc({"type": "base64", "media_type": "application/pdf", "data": b64(b"%PDF-")})]}]}
    q.documents_to_text(data)
    assert "could not be read" in texts(data)[0]


def test_openai_file_parts_and_unknown_types():
    data = {"messages": [{"role": "user", "content": [
        {"type": "file", "file": {"filename": "a.txt", "file_data": "data:text/plain;base64," + b64(b"plain words")}},
        {"type": "input_file", "filename": "b.zip", "file_data": "data:application/zip;base64," + b64(b"PK..")},
        {"type": "file", "file": {"file_id": "file-123"}},
        doc({"type": "url", "url": "https://example.com/x.pdf"}),
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "x"}},
        {"type": "text", "text": "question"},
    ]}]}
    q.documents_to_text(data)
    parts = data["messages"][0]["content"]
    assert "plain words" in parts[0]["text"]
    assert "application/zip is not supported" in parts[1]["text"]
    assert "can't fetch" in parts[2]["text"] and "can't fetch" in parts[3]["text"]
    assert parts[4]["type"] == "image" and parts[5] == {"type": "text", "text": "question"}
    assert not any(p.get("type") in ("document", "file", "input_file") for p in parts)


def test_long_documents_are_truncated(monkeypatch):
    monkeypatch.setattr(q, "MAX_DOCUMENT_CHARS", 10)
    data = {"messages": [{"role": "user", "content": [doc({"type": "text", "data": "x" * 50})]}]}
    q.documents_to_text(data)
    assert "truncated at 10 characters" in texts(data)[0]


def test_string_content_and_non_dicts_are_untouched():
    data = {"messages": [{"role": "user", "content": "hi"}], "model": "qwen3.8-27b"}
    assert q.documents_to_text(data) == {"messages": [{"role": "user", "content": "hi"}], "model": "qwen3.8-27b"}
    assert q.documents_to_text(None) is None


def test_pre_call_hook_converts_then_merges_system():
    data = {"system": "be brief", "messages": [
        {"role": "user", "content": [doc({"type": "text", "data": "spec"})]},
        {"role": "system", "content": "late rule"},
    ]}
    out = asyncio.run(q.proxy_handler_instance.async_pre_call_hook(None, None, data, "anthropic_messages"))
    assert out["system"] == "be brief\n\nlate rule"
    assert out["messages"][0]["content"][0]["type"] == "text"


def test_real_pdf_extraction():
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = __import__("io").BytesIO()
    writer.write(buf)
    text, pages = q._pdf_text(buf.getvalue())
    assert pages == 1 and text == ""
