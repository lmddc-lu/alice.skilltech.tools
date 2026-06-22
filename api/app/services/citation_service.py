"""Shared citation-building logic for chat streaming endpoints."""

import json
import logging
import re
from typing import Any

from app.services.rag_service import get_session_sources

logger = logging.getLogger(__name__)


def build_citations(
    sources: list[dict[str, Any]], response_text: str = ""
) -> list[dict[str, Any]]:
    """Build citation list from hayhooks sources.

    Each [N] in the LLM response maps to one citation. Only citations
    actually referenced in response_text are returned.
    """
    citations: list[dict[str, Any]] = []
    for idx, source in enumerate(sources):
        meta = source.get("meta", {})
        citations.append(
            {
                "id": idx + 1,
                "file_name": meta.get("filename", "unknown"),
                "file_id": meta.get("file_id"),
                "source_url": meta.get("source_url"),
                "score": source.get("score"),
            }
        )

    if response_text:
        referenced_ids = {
            int(m) for m in re.findall(r"[\[【](\d+)[\]】]", response_text)
        }
        citations = [c for c in citations if c["id"] in referenced_ids]

    return citations


def build_debug_chunks(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the full retrieved-chunks payload for the admin/owner debug view.

    Unlike :func:`build_citations`, this returns *every* retrieved chunk with its
    raw text content, regardless of whether the LLM cited it in its answer.
    """
    chunks: list[dict[str, Any]] = []
    for idx, source in enumerate(sources):
        meta = source.get("meta", {})
        chunks.append(
            {
                "id": idx + 1,
                "content": source.get("content", ""),
                "score": source.get("score"),
                "document_id": source.get("document_id"),
                "file_name": meta.get("filename", "unknown"),
                "file_id": meta.get("file_id"),
                "source_url": meta.get("source_url"),
                "chunk_index": meta.get("chunk_index"),
                "total_chunks": meta.get("total_chunks"),
                "headings": meta.get("headings", []),
            }
        )
    return chunks


def _encode_event(payload: dict[str, Any]) -> bytes:
    """Encode a dict as a single SSE ``data:`` event."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


async def fetch_and_encode_citations(
    source_doc_token: str, response_text: str = ""
) -> bytes | None:
    """Fetch sources for a session and return an encoded SSE citation event, or None."""
    try:
        sources = await get_session_sources(source_doc_token)
        if sources:
            citations = build_citations(sources, response_text)
            if not citations:
                return None
            return _encode_event({"citations": citations})
    except Exception as e:
        logger.error(f"Error fetching citations: {e}")
    return None


async def fetch_chat_trailer_events(
    source_doc_token: str,
    response_text: str = "",
    include_debug_chunks: bool = False,
) -> list[bytes]:
    """Fetch session sources once and build the trailing SSE events for a chat.

    Always yields a ``citations`` event (when any citation is referenced). When
    ``include_debug_chunks`` is set i.e. the requester is the chatbot owner or a
    platform admin also yields a ``debug_chunks`` event carrying every retrieved
    chunk's full text and retrieval metadata.
    """
    events: list[bytes] = []
    try:
        sources = await get_session_sources(source_doc_token)
        if not sources:
            return events

        citations = build_citations(sources, response_text)
        if citations:
            events.append(_encode_event({"citations": citations}))

        if include_debug_chunks:
            events.append(_encode_event({"debug_chunks": build_debug_chunks(sources)}))
    except Exception as e:
        logger.error(f"Error fetching chat trailer events: {e}")
    return events
