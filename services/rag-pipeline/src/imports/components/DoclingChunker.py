"""Haystack component wrapping docling's HybridChunker."""

import threading
from typing import Any

from docling.chunking import HybridChunker
from docling_core.types import DoclingDocument
from haystack import Document, component
from loguru import logger

# HybridChunker loads a native HF tokenizer whose freed memory glibc never
# returns to the OS, so building one per component instance accumulates RSS
# (one DoclingChunker exists per cached indexing pipeline, i.e. per index).
# Chunkers are shared process-wide per config instead. The paired lock
# serializes chunking on the shared instance: transformers fast tokenizers
# mutate internal truncation state on use and are not safe to call
# concurrently from multiple threads.
_shared_chunkers: dict[tuple[str, int, bool], tuple[HybridChunker, threading.Lock]] = {}
_shared_chunkers_lock = threading.Lock()


def _get_shared_chunker(
    tokenizer: str, max_tokens: int, merge_peers: bool
) -> tuple[HybridChunker, threading.Lock]:
    key = (tokenizer, max_tokens, merge_peers)
    with _shared_chunkers_lock:
        entry = _shared_chunkers.get(key)
        if entry is None:
            logger.info(
                f"Initializing HybridChunker with tokenizer={tokenizer}, max_tokens={max_tokens}"
            )
            entry = (
                HybridChunker(
                    tokenizer=tokenizer,
                    max_tokens=max_tokens,
                    merge_peers=merge_peers,
                ),
                threading.Lock(),
            )
            _shared_chunkers[key] = entry
        return entry


@component
class DoclingChunker:
    """Chunk DoclingDocument objects via docling's HybridChunker. CPU only."""

    def __init__(
        self,
        tokenizer: str = "sentence-transformers/all-MiniLM-L6-v2",
        max_tokens: int = 512,
        merge_peers: bool = True,
    ):
        """
        :param tokenizer: HuggingFace tokenizer. Should match the embedding model.
        :param max_tokens: max tokens per chunk.
        :param merge_peers: merge undersized consecutive chunks with same headings.
        """
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.merge_peers = merge_peers
        self._chunker = None
        self._chunk_lock = threading.Lock()

    def _get_chunker(self) -> HybridChunker:
        if self._chunker is None:
            self._chunker, self._chunk_lock = _get_shared_chunker(
                self.tokenizer, self.max_tokens, self.merge_peers
            )
        return self._chunker

    @component.output_types(documents=list[Document])
    def run(
        self,
        docling_documents: list[DoclingDocument],
        meta: dict[str, Any] | None = None,
        doc_metadata: list[dict[str, Any]] | None = None,
    ) -> dict[str, list[Document]]:
        """Chunk DoclingDocument objects into Haystack Documents.

        :param doc_metadata: per-document metadata parallel to ``docling_documents``.
            Each dict is stamped onto every chunk from its corresponding doc
            (file_id, filename, mime_type, ...).
        """
        documents = []
        meta = meta or {}
        chunker = self._get_chunker()

        with self._chunk_lock:
            documents = self._chunk_documents(
                chunker, docling_documents, meta, doc_metadata
            )

        logger.info(f"Total chunks created: {len(documents)}")
        return {"documents": documents}

    def _chunk_documents(
        self,
        chunker: HybridChunker,
        docling_documents: list[DoclingDocument],
        meta: dict[str, Any],
        doc_metadata: list[dict[str, Any]] | None,
    ) -> list[Document]:
        documents: list[Document] = []

        for doc_index, docling_doc in enumerate(docling_documents):
            try:
                per_doc_meta: dict[str, Any] = {}
                if doc_metadata and doc_index < len(doc_metadata):
                    per_doc_meta = doc_metadata[doc_index] or {}

                # caller-supplied filename is robust to format shims (e.g. .txt to .md)
                source_file = per_doc_meta.get("filename") or getattr(
                    docling_doc.origin, "filename", "unknown"
                )

                chunks = list(chunker.chunk(docling_doc))
                logger.info(f"Chunked {source_file}: {len(chunks)} chunks")

                for i, chunk in enumerate(chunks):
                    chunk_text = chunker.contextualize(chunk)

                    if not chunk_text.strip():
                        continue

                    chunk_meta = {
                        "file_name": source_file,
                        "source": source_file,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        **meta,
                    }
                    for key in (
                        "file_id",
                        "filename",
                        "mime_type",
                        "source_url",
                        "content_etag",
                        "force_ocr",
                    ):
                        value = per_doc_meta.get(key)
                        if value is not None:
                            chunk_meta[key] = value

                    if hasattr(chunk, "meta") and chunk.meta:
                        if hasattr(chunk.meta, "headings") and chunk.meta.headings:
                            chunk_meta["headings"] = chunk.meta.headings
                        if hasattr(chunk.meta, "captions") and chunk.meta.captions:
                            chunk_meta["captions"] = chunk.meta.captions

                    doc = Document(content=chunk_text, meta=chunk_meta)
                    documents.append(doc)

            except Exception as e:
                logger.error(f"Error chunking document: {e}")
                continue

        return documents
