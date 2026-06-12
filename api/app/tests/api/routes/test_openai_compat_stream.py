"""Tests for reshaping the upstream RAG SSE stream into an OpenAI-compatible one.

These target the pure ``transform_stream_chunk`` helper used by the
``/v1/chat/completions`` streaming route. They pin the compat-layer behaviour
that differs from the raw Haystack stream:

- the per-chunk ``id``, ``created`` and ``model`` are rewritten so the whole
  stream shares one ``chatcmpl-…`` id / timestamp / the chatbot's name
  (upstream echoes a per-pipeline ``rag_query-…`` id and a per-chunk
  timestamp), the way OpenAI documents its chunks;
- each event is terminated with a blank line (``\n\n``) per SSE framing;
- assistant text is extracted for citation matching;
- ``[DONE]`` lines coming from upstream are suppressed (the route emits its own
  terminator before the citations event).
"""

import json

from app.services.openai_stream_format import DONE_LINE, transform_stream_chunk

_RESPONSE_ID = "chatcmpl-test-id"
_CREATED = 1781080141


def _chunk_line(content: str | None = None, finish: str | None = None) -> str:
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    payload = {
        "id": "rag_query-abc",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "rag_query",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return "data: " + json.dumps(payload) + "\n"


def test_rewrites_id_created_and_model() -> None:
    out, content = transform_stream_chunk(
        _chunk_line(content="Hello"), "Alice kb", _RESPONSE_ID, _CREATED
    )

    forwarded = json.loads(out[len("data:") :].strip())
    assert forwarded["id"] == _RESPONSE_ID
    assert forwarded["created"] == _CREATED
    assert forwarded["model"] == "Alice kb"
    assert content == "Hello"


def test_events_are_terminated_with_blank_line() -> None:
    # SSE framing: each event ends with a blank line (\n\n).
    out, _ = transform_stream_chunk(
        _chunk_line(content="Hello"), "Alice kb", _RESPONSE_ID, _CREATED
    )
    assert out.endswith("\n\n")
    assert DONE_LINE.endswith(b"\n\n")


def test_extracts_content_and_ignores_empty_deltas() -> None:
    # The leading role-only / empty-content chunks contribute no text.
    _, empty = transform_stream_chunk(
        _chunk_line(content=""), "Alice kb", _RESPONSE_ID, _CREATED
    )
    assert empty == ""

    _, finish = transform_stream_chunk(
        _chunk_line(finish="stop"), "Alice kb", _RESPONSE_ID, _CREATED
    )
    assert finish == ""


def test_suppresses_upstream_done() -> None:
    out, content = transform_stream_chunk(
        "data: [DONE]\n", "Alice kb", _RESPONSE_ID, _CREATED
    )
    assert out == ""
    assert content == ""
    # The route, not this helper, is responsible for the terminator.
    assert DONE_LINE == b"data: [DONE]\n\n"


def test_passes_through_non_data_and_malformed_lines() -> None:
    # A comment/keepalive line and a non-JSON data line are forwarded as-is
    # rather than dropped, so the stream framing is preserved.
    out, _ = transform_stream_chunk(
        ": keep-alive\ndata: not-json\n", "Alice kb", _RESPONSE_ID, _CREATED
    )
    assert ": keep-alive" in out
    assert "data: not-json" in out


def test_preserves_non_ascii_content() -> None:
    out, content = transform_stream_chunk(
        _chunk_line(content=" café — déjà"), "Alice kb", _RESPONSE_ID, _CREATED
    )
    # ensure_ascii=False keeps the bytes readable rather than \uXXXX-escaped.
    assert " café — déjà" in out
    assert content == " café — déjà"
