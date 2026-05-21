"""Haystack component wrapping docling's HybridChunker."""

from typing import Any

from docling.chunking import HybridChunker
from docling_core.types import DoclingDocument
from haystack import Document, component
from loguru import logger


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

    def _get_chunker(self) -> HybridChunker:
        if self._chunker is None:
            logger.info(
                f"Initializing HybridChunker with tokenizer={self.tokenizer}, max_tokens={self.max_tokens}"
            )
            self._chunker = HybridChunker(
                tokenizer=self.tokenizer,
                max_tokens=self.max_tokens,
                merge_peers=self.merge_peers,
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

        logger.info(f"Total chunks created: {len(documents)}")
        return {"documents": documents}
