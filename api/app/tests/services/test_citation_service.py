from app.services.citation_service import build_citations, build_debug_chunks


def _source(idx: int, *, content: str = "chunk text", **meta) -> dict:
    return {
        "content": content,
        "score": 0.9 - idx * 0.1,
        "document_id": f"doc-{idx}",
        "meta": {
            "filename": f"file-{idx}.pdf",
            "file_id": f"f-{idx}",
            "source_url": None,
            "chunk_index": idx,
            "total_chunks": 5,
            "headings": ["Section", f"Sub {idx}"],
            **meta,
        },
    }


class TestBuildDebugChunks:
    def test_returns_every_chunk_with_full_content_regardless_of_citation(self) -> None:
        # Unlike citations, debug chunks ignore what the LLM referenced: all
        # retrieved chunks are returned so the owner/admin can inspect retrieval.
        sources = [_source(0), _source(1), _source(2)]

        chunks = build_debug_chunks(sources)

        assert len(chunks) == 3
        assert [c["id"] for c in chunks] == [1, 2, 3]
        assert chunks[0]["content"] == "chunk text"
        assert chunks[0]["file_name"] == "file-0.pdf"
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["total_chunks"] == 5
        assert chunks[0]["headings"] == ["Section", "Sub 0"]
        assert chunks[0]["score"] == 0.9

    def test_tolerates_missing_meta(self) -> None:
        chunks = build_debug_chunks([{"content": "bare", "score": None}])

        assert chunks[0]["file_name"] == "unknown"
        assert chunks[0]["headings"] == []
        assert chunks[0]["chunk_index"] is None

    def test_debug_chunks_not_filtered_by_response_text(self) -> None:
        # build_citations drops uncited entries; build_debug_chunks keeps them.
        sources = [_source(0), _source(1)]

        citations = build_citations(sources, response_text="see [1] only")
        chunks = build_debug_chunks(sources)

        assert {c["id"] for c in citations} == {1}
        assert {c["id"] for c in chunks} == {1, 2}
