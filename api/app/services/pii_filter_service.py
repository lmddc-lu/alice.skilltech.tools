"""PII redaction via the pii-filter model service (services/pii-filter).

Used by chatbots with ``pii_filter_enabled=True`` to strip personal data out of
user messages *before* they are forwarded to the LLM. The service runs a
multilingual token-classification model that detects names and structured PII
(email, phone, IBAN, ...) in one pass and returns the text with each entity
replaced by a ``[TYPE_N]`` placeholder, plus a ``{placeholder: surface}`` map.

The placeholder map lets us reverse the redaction on the way back: if the LLM
echoes a placeholder in its response, ``StreamUnredactor`` swaps the original
value back in for the user (who already owns their own PII). The LLM itself
never sees the raw data.

Fails closed: if the service is unreachable while the filter is enabled, we
raise rather than silently forwarding unredacted PII to the LLM. Opting into the
filter means PII must never leak, even at the cost of the request failing.
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.services.rag_service import HayhooksMessage

logger = logging.getLogger(__name__)

# The model runs on GPU in prod; keep a generous timeout for CPU/cold starts.
_TIMEOUT = 30.0

# A redaction placeholder: [TYPE_N], e.g. [LASTNAME_1], [EMAIL_2]. The type is
# uppercase letters/underscores, followed by _<digits>.
PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*_\d+\]")


def _remap(mapping: dict[str, str]) -> Callable[[re.Match[str]], str]:
    """Build a re.sub replacement that swaps each placeholder via `mapping`,
    leaving unknown placeholders untouched."""

    def repl(m: re.Match[str]) -> str:
        return mapping.get(m.group(0), m.group(0))

    return repl


async def redact_text(text: str) -> tuple[str, dict[str, str]]:
    """Redact PII in a single string via the pii-filter service.

    Returns ``(redacted_text, mapping)`` where mapping is ``{placeholder:
    surface}``. Returns the text unchanged with an empty mapping when there is
    nothing to scan. Raises HTTPException(502) if the service is unreachable."""
    if not text or not text.strip():
        return text, {}

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.PII_FILTER_URL}/redact",
                json={"text": text},
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("PII redaction took %.1f ms (%d chars)", elapsed_ms, len(text))
            return data.get("redacted_text", text), data.get("mapping", {})
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        # Fail closed: never forward unredacted PII when the filter is on.
        logger.error("PII filter service unavailable: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="PII filter is enabled but unavailable; chat blocked to "
            "avoid leaking personal data.",
        )
    except httpx.HTTPStatusError as exc:
        logger.error("PII filter service returned an error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="PII filter failed to process the message; chat blocked.",
        )


def _placeholder_type(placeholder: str) -> str:
    """`[LASTNAME_1]` -> `LASTNAME`."""
    return placeholder[1:].rsplit("_", 1)[0]


async def redact_messages(
    messages: list[HayhooksMessage],
) -> tuple[list[HayhooksMessage], dict[str, str]]:
    """Redact PII from user message contents, leaving roles and non-user
    messages untouched. User messages are the source of inbound PII; assistant
    and system messages are server/LLM-generated. Redaction runs concurrently.

    The pii-filter service numbers placeholders *per message*, so the same
    ``[LASTNAME_1]`` could mean different people in different messages. We
    re-number into a single conversation-wide namespace so the returned mapping
    has unambiguous keys: the same surface form always gets the same placeholder,
    distinct surfaces get distinct numbers. Returns ``(messages, mapping)``."""
    user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not user_indices:
        return messages, {}

    per_message = await asyncio.gather(
        *(redact_text(messages[i].get("content", "")) for i in user_indices)
    )

    out: list[HayhooksMessage] = [dict(m) for m in messages]  # type: ignore[misc]
    global_map: dict[str, str] = {}  # global placeholder -> surface
    surface_to_global: dict[tuple[str, str], str] = {}  # (type, surface) -> ph
    type_counts: dict[str, int] = {}

    for idx, (redacted, local_map) in zip(user_indices, per_message, strict=True):
        # Map this message's local placeholders onto global ones.
        local_to_global: dict[str, str] = {}
        for local_ph, surface in local_map.items():
            type_ = _placeholder_type(local_ph)
            key = (type_, surface.lower())
            global_ph = surface_to_global.get(key)
            if global_ph is None:
                type_counts[type_] = type_counts.get(type_, 0) + 1
                global_ph = f"[{type_}_{type_counts[type_]}]"
                surface_to_global[key] = global_ph
                global_map[global_ph] = surface
            local_to_global[local_ph] = global_ph

        # Rewrite the redacted text local->global in a single pass.
        out[idx]["content"] = PLACEHOLDER_RE.sub(_remap(local_to_global), redacted)

    return out, global_map


class StreamUnredactor:
    """Reverses redaction on a streamed LLM response, token by token.

    Placeholders can arrive split across stream chunks (``[LASTNAME`` then
    ``_1]``), so we hold back any trailing text that could still be the start of
    a placeholder until it either completes or is ruled out. Complete
    placeholders anywhere in the safe-to-emit text are swapped for their original
    surface via the mapping.

    The mapping is held by reference and read at ``feed`` time, so the caller may
    populate it after constructing the unredactor (redaction runs lazily, just
    before the first response chunk)."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping
        self._buf = ""
        self.restored: set[str] = set()

    def feed(self, text: str) -> str:
        """Add a chunk and return the text that is now safe to emit."""
        self._buf += text
        hold = self._partial_start(self._buf)
        emit, self._buf = self._buf[:hold], self._buf[hold:]
        return self._replace(emit)

    def flush(self) -> str:
        """Emit whatever is left (called when the stream ends)."""
        out = self._replace(self._buf)
        self._buf = ""
        return out

    def _replace(self, text: str) -> str:
        if not self._mapping or "[" not in text:
            return text

        def repl(m: re.Match[str]) -> str:
            key = m.group(0)
            if key in self._mapping:
                self.restored.add(key)
                return self._mapping[key]
            return key

        return PLACEHOLDER_RE.sub(repl, text)

    @staticmethod
    def _partial_start(buf: str) -> int:
        """Index from which `buf` might be an unfinished placeholder.

        Everything before it is safe to emit. A trailing ``[`` whose following
        chars are all valid placeholder-body characters (and which has no closing
        ``]`` yet) is held back; anything else is safe."""
        i = buf.rfind("[")
        if i == -1 or "]" in buf[i:]:
            return len(buf)  # no open bracket, or it already closed
        body = buf[i + 1 :]
        if all(c.isupper() or c.isdigit() or c == "_" for c in body):
            return i  # could still grow into [TYPE_N]
        return len(buf)  # contains a char a placeholder can't -> not one
