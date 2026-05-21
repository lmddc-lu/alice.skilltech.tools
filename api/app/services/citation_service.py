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
            citation_event = json.dumps({"citations": citations})
            return f"data: {citation_event}\n\n".encode()
    except Exception as e:
        logger.error(f"Error fetching citations: {e}")
    return None
