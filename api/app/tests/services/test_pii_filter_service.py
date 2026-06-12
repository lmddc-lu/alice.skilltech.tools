"""Tests for the pii-filter-service client and response un-redaction.

The pii-filter model service is stubbed with an httpx.MockTransport so the
tests never touch the network or load the model.
"""

import httpx
import pytest
from fastapi import HTTPException

from app.services import pii_filter_service
from app.services.pii_filter_service import (
    StreamUnredactor,
    redact_messages,
    redact_text,
)


def _install_transport(monkeypatch, handler) -> None:
    """Make pii_filter_service build AsyncClients backed by `handler`."""
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(pii_filter_service.httpx, "AsyncClient", factory)


def _redact_handler(request: httpx.Request) -> httpx.Response:
    """Stub /redact: replace an email-looking string and return its mapping."""
    if request.url.path == "/redact":
        return httpx.Response(
            200,
            json={
                "redacted_text": "contact [EMAIL_1]",
                "entities": [],
                "mapping": {"[EMAIL_1]": "jean@lmddc.lu"},
            },
        )
    return httpx.Response(404)


# --- redact_text ------------------------------------------------------------


async def test_redacts_pii_and_returns_mapping(monkeypatch):
    _install_transport(monkeypatch, _redact_handler)
    out, mapping = await redact_text("contact jean@lmddc.lu")
    assert out == "contact [EMAIL_1]"
    assert mapping == {"[EMAIL_1]": "jean@lmddc.lu"}


async def test_blank_text_short_circuits(monkeypatch):
    def boom(_request):
        raise AssertionError("PII service should not be called for blank text")

    _install_transport(monkeypatch, boom)
    out, mapping = await redact_text("   ")
    assert out == "   "
    assert mapping == {}


async def test_request_sends_text_to_redact_endpoint(monkeypatch):
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"redacted_text": "ok", "entities": [], "mapping": {}}
        )

    _install_transport(monkeypatch, handler)
    await redact_text("my name is Romain")
    assert seen["path"] == "/redact"
    assert seen["body"] == {"text": "my name is Romain"}


async def test_fails_closed_when_service_unreachable(monkeypatch):
    def unreachable(_request):
        raise httpx.ConnectError("connection refused")

    _install_transport(monkeypatch, unreachable)
    with pytest.raises(HTTPException) as exc:
        await redact_text("contact jean@lmddc.lu")
    assert exc.value.status_code == 502


async def test_fails_closed_on_service_http_error(monkeypatch):
    def server_error(_request):
        return httpx.Response(500, json={"error": "boom"})

    _install_transport(monkeypatch, server_error)
    with pytest.raises(HTTPException) as exc:
        await redact_text("contact jean@lmddc.lu")
    assert exc.value.status_code == 502


# --- redact_messages --------------------------------------------------------


async def test_redact_messages_only_touches_user_role(monkeypatch):
    _install_transport(monkeypatch, _redact_handler)
    messages = [
        {"role": "system", "content": "you are a helpful assistant jean@lmddc.lu"},
        {"role": "user", "content": "contact jean@lmddc.lu"},
        {"role": "assistant", "content": "sure, jean@lmddc.lu noted"},
    ]
    out, mapping = await redact_messages(messages)

    assert out[1]["content"] == "contact [EMAIL_1]"
    assert out[0]["content"] == messages[0]["content"]
    assert out[2]["content"] == messages[2]["content"]
    assert mapping == {"[EMAIL_1]": "jean@lmddc.lu"}
    # input not mutated in place
    assert messages[1]["content"] == "contact jean@lmddc.lu"


async def test_redact_messages_no_user_messages_is_noop(monkeypatch):
    def boom(_request):
        raise AssertionError("PII service should not be called with no user messages")

    _install_transport(monkeypatch, boom)
    messages = [{"role": "assistant", "content": "hi"}]
    out, mapping = await redact_messages(messages)
    assert out == messages
    assert mapping == {}


async def test_redact_messages_renumbers_collisions_globally(monkeypatch):
    # Each message is redacted independently and both get a local [EMAIL_1];
    # the second must be renumbered to [EMAIL_2] in the conversation namespace.
    async def fake_redact_text(text: str):
        if "jean" in text:
            return "contact [EMAIL_1]", {"[EMAIL_1]": "jean@lmddc.lu"}
        if "marie" in text:
            return "ping [EMAIL_1]", {"[EMAIL_1]": "marie@lmddc.lu"}
        return text, {}

    monkeypatch.setattr(pii_filter_service, "redact_text", fake_redact_text)
    messages = [
        {"role": "user", "content": "contact jean@lmddc.lu"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "and marie@lmddc.lu"},
    ]
    out, mapping = await redact_messages(messages)
    assert out[0]["content"] == "contact [EMAIL_1]"
    assert out[2]["content"] == "ping [EMAIL_2]"
    assert mapping == {
        "[EMAIL_1]": "jean@lmddc.lu",
        "[EMAIL_2]": "marie@lmddc.lu",
    }


async def test_redact_messages_same_surface_shares_global_placeholder(monkeypatch):
    async def fake_redact_text(_text: str):
        return "x [EMAIL_1]", {"[EMAIL_1]": "jean@lmddc.lu"}

    monkeypatch.setattr(pii_filter_service, "redact_text", fake_redact_text)
    messages = [
        {"role": "user", "content": "jean@lmddc.lu first"},
        {"role": "user", "content": "jean@lmddc.lu again"},
    ]
    out, mapping = await redact_messages(messages)
    # Same surface in both messages -> same placeholder, single map entry.
    assert out[0]["content"] == "x [EMAIL_1]"
    assert out[1]["content"] == "x [EMAIL_1]"
    assert mapping == {"[EMAIL_1]": "jean@lmddc.lu"}


# --- StreamUnredactor -------------------------------------------------------


def test_unredactor_replaces_complete_placeholder():
    u = StreamUnredactor({"[LASTNAME_1]": "DUPONT"})
    assert u.feed("Your name is [LASTNAME_1].") + u.flush() == "Your name is DUPONT."


def test_unredactor_handles_placeholder_split_across_chunks():
    u = StreamUnredactor({"[LASTNAME_1]": "DUPONT"})
    out = ""
    for tok in ["Hello ", "[LAST", "NAME", "_1", "]", "!"]:
        out += u.feed(tok)
    out += u.flush()
    assert out == "Hello DUPONT!"


def test_unredactor_passthrough_without_mapping():
    u = StreamUnredactor({})
    out = "".join(u.feed(t) for t in ["a", "[B", "C]"]) + u.flush()
    assert out == "a[BC]"


def test_unredactor_leaves_citation_markers():
    u = StreamUnredactor({"[LASTNAME_1]": "DUPONT"})
    out = u.feed("see [1] and [LASTNAME_1]") + u.flush()
    assert out == "see [1] and DUPONT"


def test_unredactor_reads_mapping_lazily():
    # The map is populated after the unredactor is constructed (redaction runs
    # just before the first response chunk).
    mapping: dict[str, str] = {}
    u = StreamUnredactor(mapping)
    mapping["[LASTNAME_1]"] = "DUPONT"
    assert u.feed("hi [LASTNAME_1]") + u.flush() == "hi DUPONT"


def test_unredactor_flushes_unclosed_tail():
    # If the stream ends mid-placeholder, emit the held text verbatim.
    u = StreamUnredactor({"[LASTNAME_1]": "DUPONT"})
    assert u.feed("end [LASTNA") == "end "
    assert u.flush() == "[LASTNA"


def test_unredactor_tracks_restored_keys_only():
    # `restored` records which placeholders were swapped (keys, not PII values),
    # for privacy-safe audit logging.
    u = StreamUnredactor({"[LASTNAME_1]": "DUPONT", "[EMAIL_1]": "a@b.lu"})
    u.feed("hi [LASTNAME_1], not [UNKNOWN_9]")
    u.flush()
    assert u.restored == {"[LASTNAME_1]"}
