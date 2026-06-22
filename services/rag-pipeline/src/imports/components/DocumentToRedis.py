from typing import Any

from haystack import component
from haystack.dataclasses import Document
from loguru import logger
from RedisSessionManager import RedisSessionManager


@component
class DocumentToRedisComponent:
    """Send documents to Redis and pass them through."""

    def __init__(self, session_manager: RedisSessionManager | None = None):
        self.session_manager = session_manager

    @component.output_types(documents=list[Document], session_id=str | None)
    def run(
        self, documents: list[Document], session_id: str | None = None
    ) -> dict[str, Any]:
        """Store documents in Redis and pass them through.

        :param session_id: optional, generated if not provided.
        """
        result_session_id = None

        if self.session_manager and documents:
            try:
                sources = self._format_sources(documents)

                result_session_id = self.session_manager.create_session(
                    sources, session_id
                )

                logger.info(
                    f"Stored {len(sources)} sources in session {result_session_id}"
                )

            except Exception as e:
                logger.warning(f"Failed to store documents in Valkey: {e}")

        return {"documents": documents, "session_id": result_session_id}

    def _format_sources(self, documents: list[Document]) -> list[dict[str, Any]]:
        sources = []
        for doc in documents:
            source = {
                "content": doc.content,
                "score": doc.score,
                "document_id": doc.id,
            }

            if doc.meta:
                source["meta"] = {
                    "filename": doc.meta.get("filename")
                    or doc.meta.get("file_name", "unknown"),
                    "mimetype": doc.meta.get("mime_type", "unknown"),
                    "file_id": doc.meta.get("file_id"),
                    "source_url": doc.meta.get("source_url"),
                    # Retrieval metadata, surfaced in the admin/owner debug view.
                    "chunk_index": doc.meta.get("chunk_index"),
                    "total_chunks": doc.meta.get("total_chunks"),
                    "headings": doc.meta.get("headings", []),
                }

            sources.append(source)

        return sources
