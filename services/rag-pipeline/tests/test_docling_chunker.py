"""Unit tests for DoclingChunker.

Locks in the contract: per-document metadata (file_id, filename, mime_type,
source_url) comes from doc_metadata and is stamped on every chunk,
regardless of docling_doc.origin.filename.

Background: docling-serve doesn't accept .txt, so DoclingServeConverter
writes a sibling .md and submits that. Before the refactor the shim
filename leaked through and chunks got labelled notes.md instead of
notes.txt. The doc_metadata contract decouples the shim from downstream.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def chunker_cls():
    # import inside fixture so conftest stubs land in sys.modules first
    from DoclingChunker import DoclingChunker

    return DoclingChunker


def _fake_chunk(text: str, headings: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        meta=SimpleNamespace(headings=headings or [], captions=[]),
    )


def _install_fake_chunker(chunker, chunks_per_doc: list[SimpleNamespace]):
    """Replace the lazy HybridChunker with a deterministic fake."""

    class _FakeHybrid:
        def chunk(self, _docling_doc):
            return list(chunks_per_doc)

        def contextualize(self, chunk):
            return chunk.text

    chunker._chunker = _FakeHybrid()


def _fake_docling_doc(origin_filename: str) -> SimpleNamespace:
    return SimpleNamespace(origin=SimpleNamespace(filename=origin_filename))


class TestDocMetadataStamping:
    def test_chunks_take_filename_and_file_id_from_doc_metadata(self, chunker_cls):
        """Regression: .txt to .md shim must not leak into chunk metadata."""
        chunker = chunker_cls()
        _install_fake_chunker(chunker, [_fake_chunk("body 1"), _fake_chunk("body 2")])

        docling_doc = _fake_docling_doc(origin_filename="notes.md")  # shim name
        doc_metadata = [
            {
                "file_id": "uuid-abc",
                "filename": "notes.txt",  # user-facing name
                "mime_type": "text/plain",
            }
        ]

        result = chunker.run(docling_documents=[docling_doc], doc_metadata=doc_metadata)
        documents = result["documents"]

        assert len(documents) == 2
        for doc in documents:
            assert doc.meta["file_id"] == "uuid-abc"
            assert doc.meta["filename"] == "notes.txt"
            assert doc.meta["mime_type"] == "text/plain"
            # use the user-facing filename, not "notes.md"
            assert doc.meta["file_name"] == "notes.txt"
            assert doc.meta["source"] == "notes.txt"

    def test_source_url_is_propagated_when_present(self, chunker_cls):
        chunker = chunker_cls()
        _install_fake_chunker(chunker, [_fake_chunk("body")])

        docling_doc = _fake_docling_doc(origin_filename="page.html")
        doc_metadata = [
            {
                "file_id": "uuid-1",
                "filename": "page.html",
                "source_url": "https://example.com/page",
            }
        ]

        documents = chunker.run(
            docling_documents=[docling_doc], doc_metadata=doc_metadata
        )["documents"]

        assert documents[0].meta["source_url"] == "https://example.com/page"

    def test_content_etag_is_propagated_when_present(self, chunker_cls):
        # incremental syncs compare this stamp against the storage etag to
        # skip unchanged files
        chunker = chunker_cls()
        _install_fake_chunker(chunker, [_fake_chunk("body")])

        docling_doc = _fake_docling_doc(origin_filename="doc.pdf")
        doc_metadata = [
            {
                "file_id": "uuid-1",
                "filename": "doc.pdf",
                "content_etag": "abc123etag",
            }
        ]

        documents = chunker.run(
            docling_documents=[docling_doc], doc_metadata=doc_metadata
        )["documents"]

        assert documents[0].meta["content_etag"] == "abc123etag"

    def test_per_document_metadata_is_not_cross_contaminated(self, chunker_cls):
        """Two docs, two metadata entries. Chunks must carry their own."""
        chunker = chunker_cls()

        class _FakeHybrid:
            def chunk(self, docling_doc):
                # chunk text identifies the source doc so assertions can
                # match metadata to chunk
                return [_fake_chunk(f"body-of-{docling_doc.origin.filename}")]

            def contextualize(self, chunk):
                return chunk.text

        chunker._chunker = _FakeHybrid()

        docs = [
            _fake_docling_doc(origin_filename="a.md"),
            _fake_docling_doc(origin_filename="b.md"),
        ]
        doc_metadata = [
            {"file_id": "uuid-a", "filename": "a.txt"},
            {"file_id": "uuid-b", "filename": "b.pdf", "mime_type": "application/pdf"},
        ]

        documents = chunker.run(docling_documents=docs, doc_metadata=doc_metadata)[
            "documents"
        ]

        assert len(documents) == 2
        by_file_id = {d.meta["file_id"]: d for d in documents}
        assert by_file_id["uuid-a"].meta["filename"] == "a.txt"
        assert by_file_id["uuid-a"].meta["file_name"] == "a.txt"
        assert "mime_type" not in by_file_id["uuid-a"].meta
        assert by_file_id["uuid-b"].meta["filename"] == "b.pdf"
        assert by_file_id["uuid-b"].meta["mime_type"] == "application/pdf"

    def test_falls_back_to_origin_filename_when_no_doc_metadata(self, chunker_cls):
        """Back-compat: calls without doc_metadata keep old behaviour."""
        chunker = chunker_cls()
        _install_fake_chunker(chunker, [_fake_chunk("body")])

        docling_doc = _fake_docling_doc(origin_filename="legacy.pdf")

        documents = chunker.run(docling_documents=[docling_doc])["documents"]

        assert len(documents) == 1
        assert documents[0].meta["file_name"] == "legacy.pdf"
        assert documents[0].meta["source"] == "legacy.pdf"
        assert "file_id" not in documents[0].meta

    def test_empty_chunk_text_is_skipped(self, chunker_cls):
        chunker = chunker_cls()
        _install_fake_chunker(
            chunker, [_fake_chunk("   "), _fake_chunk("real content")]
        )

        documents = chunker.run(
            docling_documents=[_fake_docling_doc("x.md")],
            doc_metadata=[{"file_id": "u", "filename": "x.txt"}],
        )["documents"]

        assert len(documents) == 1
        assert documents[0].content == "real content"

    def test_mismatched_doc_metadata_length_does_not_crash(self, chunker_cls):
        """doc_metadata shorter than docling_documents: extras get empty meta."""
        chunker = chunker_cls()
        _install_fake_chunker(chunker, [_fake_chunk("body")])

        docs = [
            _fake_docling_doc("a.md"),
            _fake_docling_doc("b.md"),
        ]
        doc_metadata = [{"file_id": "uuid-a", "filename": "a.txt"}]

        documents = chunker.run(docling_documents=docs, doc_metadata=doc_metadata)[
            "documents"
        ]

        assert len(documents) == 2
        a_doc = next(d for d in documents if d.meta.get("file_id") == "uuid-a")
        assert a_doc.meta["filename"] == "a.txt"
        b_doc = next(d for d in documents if "file_id" not in d.meta)
        assert b_doc.meta["file_name"] == "b.md"
