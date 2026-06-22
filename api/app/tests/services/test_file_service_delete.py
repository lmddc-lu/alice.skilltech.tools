"""Tests for FileService.delete_files_from_selections.

Deselecting a file must fully reap it (UploadedFile row + S3 object), and
emptying a link must drop the now-orphan FILE datasource. These guard
against the ``db.unselected_uploaded_files`` / ``db.orphan_datasources``
leaks. Storage is mocked; no MinIO is touched.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

from sqlmodel import Session, select

from app.models.enums import SourceType
from app.models.tables import (
    DataSource,
    KnowledgeBase,
    KnowledgeBaseDatasourceLink,
    UploadedFile,
    User,
)
from app.services.file_service import FileService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service() -> tuple[FileService, MagicMock]:
    """FileService with a mocked storage manager. Returns (service, storage)."""
    upload_manager = MagicMock()
    storage = MagicMock()
    upload_manager.storage = storage
    return FileService(upload_manager=upload_manager), storage


def _kb(db: Session, user: User) -> KnowledgeBase:
    kb = KnowledgeBase(name="kb", user_id=user.id)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


def _datasource(db: Session, user: User) -> DataSource:
    ds = DataSource(name="ds", source_type=SourceType.FILE.value, owner_id=user.id)
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def _uploaded_file(db: Session, ds: DataSource, name: str = "x.pdf") -> UploadedFile:
    uf = UploadedFile(
        datasource_id=ds.id,
        original_filename=name,
        stored_filename=name,
        file_size=10,
        mime_type="application/pdf",
        file_hash="h",
        storage_path=f"u@e/ns/datasources/{ds.id}/uploads/{name}",
    )
    db.add(uf)
    db.commit()
    db.refresh(uf)
    return uf


def _link(
    db: Session,
    kb: KnowledgeBase,
    ds: DataSource,
    file_ids: list[uuid.UUID],
) -> KnowledgeBaseDatasourceLink:
    link = KnowledgeBaseDatasourceLink(
        knowledge_base_id=kb.id,
        datasource_id=ds.id,
        selection=json.dumps([f"file:{fid}" for fid in file_ids]),
    )
    db.add(link)
    db.commit()
    return link


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_removing_one_file_deletes_row_and_s3(db: Session, test_user: User) -> None:
    kb = _kb(db, test_user)
    ds = _datasource(db, test_user)
    keep = _uploaded_file(db, ds, "keep.pdf")
    drop = _uploaded_file(db, ds, "drop.pdf")
    link = _link(db, kb, ds, [keep.id, drop.id])

    service, storage = _service()
    deleted = service.delete_files_from_selections(db, [link], [str(drop.id)])

    assert deleted == [str(drop.id)]
    # dropped row is gone, kept row survives
    assert db.get(UploadedFile, drop.id) is None
    assert db.get(UploadedFile, keep.id) is not None
    # selection now references only the kept file
    assert json.loads(link.selection) == [f"file:{keep.id}"]
    # datasource still alive (link not empty)
    assert db.get(DataSource, ds.id) is not None
    # S3 object of the dropped file was deleted, the kept one was not
    storage.delete_file.assert_called_once_with(drop.storage_path)


def test_removing_last_file_deletes_orphan_datasource(
    db: Session, test_user: User
) -> None:
    kb = _kb(db, test_user)
    ds = _datasource(db, test_user)
    only = _uploaded_file(db, ds, "only.pdf")
    link = _link(db, kb, ds, [only.id])
    link_pk = (link.knowledge_base_id, link.datasource_id)

    service, storage = _service()
    service.delete_files_from_selections(db, [link], [str(only.id)])

    # row, link, and now-orphan datasource all gone
    assert db.get(UploadedFile, only.id) is None
    assert db.get(DataSource, ds.id) is None
    assert db.get(KnowledgeBaseDatasourceLink, link_pk) is None
    storage.delete_file.assert_called_once_with(only.storage_path)


def test_s3_failure_still_commits_db_deletes(db: Session, test_user: User) -> None:
    kb = _kb(db, test_user)
    ds = _datasource(db, test_user)
    drop = _uploaded_file(db, ds, "drop.pdf")
    link = _link(db, kb, ds, [drop.id])

    service, storage = _service()
    storage.delete_file.side_effect = RuntimeError("S3 unreachable")

    # must not raise, S3 cleanup is best-effort after commit
    deleted = service.delete_files_from_selections(db, [link], [str(drop.id)])

    assert deleted == [str(drop.id)]
    # DB deletes committed despite the S3 error
    assert db.get(UploadedFile, drop.id) is None
    assert db.get(DataSource, ds.id) is None


def test_datasource_kept_when_other_link_references_it(
    db: Session, test_user: User
) -> None:
    """A datasource shared by two links must survive emptying one of them."""
    kb_a = _kb(db, test_user)
    kb_b = _kb(db, test_user)
    ds = _datasource(db, test_user)
    file_a = _uploaded_file(db, ds, "a.pdf")
    file_b = _uploaded_file(db, ds, "b.pdf")
    link_a = _link(db, kb_a, ds, [file_a.id])
    _link(db, kb_b, ds, [file_b.id])

    service, _ = _service()
    service.delete_files_from_selections(db, [link_a], [str(file_a.id)])

    # link_a emptied → deleted, but ds still referenced by link_b → kept
    assert db.get(UploadedFile, file_a.id) is None
    assert db.get(DataSource, ds.id) is not None
    # the other link's file is untouched
    assert db.get(UploadedFile, file_b.id) is not None
    remaining = db.exec(
        select(KnowledgeBaseDatasourceLink).where(
            KnowledgeBaseDatasourceLink.datasource_id == ds.id
        )
    ).all()
    assert len(remaining) == 1
