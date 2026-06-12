"""Pure helpers for reshaping the upstream RAG SSE stream into an
OpenAI-compatible stream.

Kept dependency-free (only ``json``) so it can be unit-tested without importing
the route layer, which pulls in storage/database clients at import time.
"""

import json

# OpenAI-style terminator. Emitted by the compat layer itself; any [DONE]
# arriving from upstream is suppressed so there is exactly one, in a known
# position (before the trailing citations event). Terminated with a blank line
# per the SSE framing rule, like every other event we emit.
DONE_LINE = b"data: [DONE]\n\n"


def transform_stream_chunk(
    text: str, model: str, response_id: str, created: int
) -> tuple[str, str]:
    """Rewrite one raw SSE chunk and pull out its assistant text.

    ``text`` is the decoded upstream chunk (one or more ``data:`` lines).
    Returns ``(out, content)`` where ``out`` is the SSE text to forward to the
    client and ``content`` is the assistant text contained in this chunk
    (for citation matching).

    Transformations applied, so the stream lines up with our own non-streaming
    response and with OpenAI's spec:

    - every chunk's ``id`` is set to ``response_id`` and ``created`` to
      ``created`` so the whole response shares one id and timestamp, the way
      OpenAI documents its chunks (upstream emits a per-pipeline ``rag_query-…``
      id and a per-chunk timestamp). The shared id is what callers use to
      correlate chunks; the shared timestamp is cosmetic but matches OpenAI;
    - every chunk's ``model`` field is set to ``model`` (the chatbot's name),
      since upstream echoes the pipeline name;
    - upstream ``data: [DONE]`` lines are dropped, the caller emits its own
      terminator once the citations event has been appended;
    - each event is terminated with a blank line (``\\n\\n``) per the SSE
      framing rule.
    """
    out = ""
    content_parts: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("data:"):
            out += raw_line + "\n\n"
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            out += raw_line + "\n\n"
            continue
        parsed["id"] = response_id
        parsed["created"] = created
        parsed["model"] = model
        try:
            delta = parsed.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                content_parts.append(content)
        except (IndexError, AttributeError):
            pass
        out += "data: " + json.dumps(parsed, ensure_ascii=False) + "\n\n"
    return out, "".join(content_parts)
