"""Unit tests for DoclingServeConverter.

The .txt to .md shim: docling-serve does not accept .txt input, so the
converter writes a sibling .md and submits that. Temporary workaround until
docling-serve picks up the upstream fix. Without it, chunks ended up
labelled foo.md instead of foo.txt because the shim filename leaked into
Qdrant.

Contract under test:

* path_metadata lookup works by full path or basename
* .txt to .md shim is cleaned up, even on the happy path
* DoclingDocument.origin.filename reflects the user-facing filename, never
  the shim
* doc_metadata is a parallel list aligned with docling_documents
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def converter_cls():
    from DoclingServeConverter import DoclingServeConverter

    return DoclingServeConverter


@pytest.fixture
def make_converter(converter_cls):
    def _make():
        return converter_cls(url="http://fake", timeout=1.0)

    return _make


def _stub_conversion_chain(converter, *, origin_filename_seen_by_docling: str):
    """Replace the docling-serve round-trip with in-process fakes.

    Returned dict records the display name submitted/polled with so tests
    can assert log/display path stayed consistent.
    """
    seen: dict[str, list[str]] = {"submitted": [], "polled": []}

    def fake_submit(_client, file_path: Path) -> str:
        seen["submitted"].append(file_path.name)
        return "task-123"

    def fake_poll(_client, _task_id, file_name):
        seen["polled"].append(file_name)
        return {"status": "success", "processing_time": 0.01}

    def fake_extract(_result):
        # docling-serve returns origin.filename = whatever was submitted
        # (the .md shim for text files)
        return SimpleNamespace(
            origin=SimpleNamespace(filename=origin_filename_seen_by_docling),
        )

    converter._submit_file_async = fake_submit
    converter._poll_for_result = fake_poll
    converter._extract_docling_document = fake_extract
    return seen


class TestTextFileShim:
    def test_txt_shim_is_cleaned_up_and_filename_restored(
        self, make_converter, tmp_path
    ):
        """Regression: .md sibling used to leak and chunks ended up labelled notes.md."""
        source = tmp_path / "notes.txt"
        source.write_text("hello world", encoding="utf-8")

        converter = make_converter()
        _stub_conversion_chain(converter, origin_filename_seen_by_docling="notes.md")

        result = converter.run(
            paths=[str(source)],
            path_metadata={
                str(source): {
                    "file_id": "uuid-1",
                    "filename": "notes.txt",
                    "mime_type": "text/plain",
                }
            },
        )

        assert result["failed_files"] == []
        assert len(result["docling_documents"]) == 1
        assert not (tmp_path / "notes.md").exists(), ".md shim file was not cleaned up"
        # caller owns the original .txt
        assert source.exists()
        docling_doc = result["docling_documents"][0]
        assert docling_doc.origin.filename == "notes.txt"

    def test_shim_cleanup_runs_even_on_conversion_failure(
        self, make_converter, tmp_path
    ):
        source = tmp_path / "notes.txt"
        source.write_text("hello", encoding="utf-8")

        converter = make_converter()

        def boom(*_a, **_k):
            raise RuntimeError("docling exploded")

        converter._submit_file_async = boom
        converter._poll_for_result = lambda *a, **k: None  # type: ignore[assignment]
        converter._extract_docling_document = lambda *a, **k: None  # type: ignore[assignment]

        result = converter.run(
            paths=[str(source)],
            path_metadata={str(source): {"file_id": "u", "filename": "notes.txt"}},
        )

        assert result["docling_documents"] == []
        assert len(result["failed_files"]) == 1
        assert result["failed_files"][0]["filename"] == "notes.txt"
        # cleanup runs in finally
        assert not (tmp_path / "notes.md").exists()


class TestDocMetadataOutput:
    def test_doc_metadata_is_parallel_to_docling_documents(
        self, make_converter, tmp_path
    ):
        path_a = tmp_path / "a.pdf"
        path_a.write_bytes(b"%PDF-1.4\n%fake")
        path_b = tmp_path / "b.pdf"
        path_b.write_bytes(b"%PDF-1.4\n%fake")

        converter = make_converter()
        _stub_conversion_chain(converter, origin_filename_seen_by_docling="ignored")

        path_metadata = {
            str(path_a): {"file_id": "uuid-a", "filename": "a.pdf"},
            str(path_b): {"file_id": "uuid-b", "filename": "b.pdf"},
        }

        result = converter.run(
            paths=[str(path_a), str(path_b)], path_metadata=path_metadata
        )

        assert len(result["docling_documents"]) == 2
        assert len(result["doc_metadata"]) == 2
        # input order preserved
        assert result["doc_metadata"][0]["file_id"] == "uuid-a"
        assert result["doc_metadata"][1]["file_id"] == "uuid-b"
        # origin.filename overridden to user-facing name
        assert result["docling_documents"][0].origin.filename == "a.pdf"
        assert result["docling_documents"][1].origin.filename == "b.pdf"

    def test_path_metadata_lookup_falls_back_to_basename(
        self, make_converter, tmp_path
    ):
        """path_metadata may be keyed by basename instead of full path."""
        path_a = tmp_path / "report.pdf"
        path_a.write_bytes(b"%PDF-1.4\n")

        converter = make_converter()
        _stub_conversion_chain(converter, origin_filename_seen_by_docling="ignored")

        # keyed by basename
        path_metadata = {"report.pdf": {"file_id": "uuid-r", "filename": "report.pdf"}}

        result = converter.run(paths=[str(path_a)], path_metadata=path_metadata)

        assert result["doc_metadata"] == [
            {"file_id": "uuid-r", "filename": "report.pdf"}
        ]

    def test_run_without_path_metadata_still_works(self, make_converter, tmp_path):
        """Back-compat path: no metadata supplied."""
        path_a = tmp_path / "legacy.pdf"
        path_a.write_bytes(b"%PDF-1.4\n")

        converter = make_converter()
        _stub_conversion_chain(converter, origin_filename_seen_by_docling="legacy.pdf")

        result = converter.run(paths=[str(path_a)])

        assert len(result["docling_documents"]) == 1
        assert result["doc_metadata"] == [{}]
        # no caller override, docling's filename is used
        assert result["docling_documents"][0].origin.filename == "legacy.pdf"
