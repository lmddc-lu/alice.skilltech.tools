"""Tests for delete_documents, focused on rename-proof file_id deletion.

Deleting by the stable meta.file_id must work even when a converter changed
the on-disk filename (so origin-filename matching would miss the chunks).
"""

from __future__ import annotations

from tests.conftest import StubDocument


def _delete_documents():
    # import inside the helper so conftest stubs are installed first
    from pipeline_wrappers.document_management.operations import delete_documents

    return delete_documents


class _FakeStore:
    def __init__(self, docs: list) -> None:
        self._docs = docs
        self.deleted_ids: list[str] = []

    def filter_documents(self, filters=None):
        if not filters:
            return list(self._docs)
        field, value = filters["field"], filters["value"]
        return [
            d
            for d in self._docs
            if field == "meta.file_id" and d.meta.get("file_id") == value
        ]

    def delete_documents(self, document_ids):
        self.deleted_ids.extend(document_ids)
        self._docs = [d for d in self._docs if d.id not in document_ids]


def test_delete_by_file_id_is_rename_proof():
    """The chunks' origin filename was renamed by the converter, but the
    stable file_id still matches and they are deleted."""
    delete_documents = _delete_documents()
    docs = [
        StubDocument(
            meta={
                "file_id": "moodle_file_34_170_21569",
                # converter renamed the file; origin filename no longer
                # matches the storage basename
                "dl_meta": {"meta": {"origin": {"filename": "converted.pdf"}}},
            },
            id="a",
        ),
        StubDocument(meta={"file_id": "moodle_file_34_170_21569"}, id="b"),
        StubDocument(meta={"file_id": "moodle_file_99_1_2"}, id="c"),
    ]
    store = _FakeStore(docs)

    result = delete_documents(store, file_ids=["moodle_file_34_170_21569"])

    assert result["success"] is True
    assert result["total_documents_removed"] == 2
    assert set(store.deleted_ids) == {"a", "b"}


def test_unknown_file_id_removes_nothing():
    delete_documents = _delete_documents()
    store = _FakeStore([StubDocument(meta={"file_id": "x"}, id="a")])

    result = delete_documents(store, file_ids=["does-not-exist"])

    assert result["success"] is True
    assert result["total_documents_removed"] == 0
    assert store.deleted_ids == []


def test_delete_requires_at_least_one_selector():
    delete_documents = _delete_documents()
    result = delete_documents(_FakeStore([]))

    assert result["success"] is False
    assert "No file_ids" in result["error"]
