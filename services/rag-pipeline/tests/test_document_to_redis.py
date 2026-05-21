"""Unit tests for DocumentToRedisComponent."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.conftest import StubDocument


@pytest.fixture
def component_cls():
    # import inside fixture so conftest stubs are installed first
    from DocumentToRedis import DocumentToRedisComponent

    return DocumentToRedisComponent


class TestFormatSources:
    def test_formats_minimal_document(self, component_cls):
        component = component_cls(session_manager=None)
        doc = StubDocument(content="hello", id="d1", score=0.9)

        sources = component._format_sources([doc])

        assert sources == [{"content": "hello", "score": 0.9, "document_id": "d1"}]

    def test_includes_meta_when_present(self, component_cls):
        component = component_cls(session_manager=None)
        doc = StubDocument(
            content="body",
            id="d2",
            score=0.5,
            meta={
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "file_id": "f-1",
                "source_url": "https://example.com/r.pdf",
            },
        )

        sources = component._format_sources([doc])

        assert sources[0]["meta"] == {
            "filename": "report.pdf",
            "mimetype": "application/pdf",
            "file_id": "f-1",
            "source_url": "https://example.com/r.pdf",
        }

    def test_falls_back_from_filename_to_file_name(self, component_cls):
        component = component_cls(session_manager=None)
        doc = StubDocument(content="x", id="d3", meta={"file_name": "alt.txt"})

        sources = component._format_sources([doc])

        assert sources[0]["meta"]["filename"] == "alt.txt"

    def test_uses_unknown_when_no_filename(self, component_cls):
        component = component_cls(session_manager=None)
        doc = StubDocument(content="x", id="d4", meta={"unrelated": "field"})

        sources = component._format_sources([doc])

        assert sources[0]["meta"]["filename"] == "unknown"
        assert sources[0]["meta"]["mimetype"] == "unknown"


class TestRun:
    def test_run_without_session_manager_returns_none_session(self, component_cls):
        component = component_cls(session_manager=None)
        docs = [StubDocument(content="hi", id="d1")]

        result = component.run(documents=docs)

        assert result["documents"] is docs
        assert result["session_id"] is None

    def test_run_calls_session_manager_create_session(self, component_cls):
        manager = MagicMock()
        manager.create_session.return_value = "session-xyz"
        component = component_cls(session_manager=manager)

        docs = [StubDocument(content="a", id="d1")]
        result = component.run(documents=docs, session_id="my-id")

        assert result["session_id"] == "session-xyz"
        manager.create_session.assert_called_once()
        sources_arg, session_arg = manager.create_session.call_args.args
        assert session_arg == "my-id"
        assert sources_arg[0]["document_id"] == "d1"

    def test_run_swallows_session_manager_errors(self, component_cls):
        manager = MagicMock()
        manager.create_session.side_effect = RuntimeError("redis down")
        component = component_cls(session_manager=manager)

        result = component.run(documents=[StubDocument(content="x", id="d1")])

        assert result["session_id"] is None  # swallowed so pipeline continues

    def test_run_with_empty_documents_skips_redis(self, component_cls):
        manager = MagicMock()
        component = component_cls(session_manager=manager)

        result = component.run(documents=[])

        manager.create_session.assert_not_called()
        assert result["documents"] == []
        assert result["session_id"] is None
