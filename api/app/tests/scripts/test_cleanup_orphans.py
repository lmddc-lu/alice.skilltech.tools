"""Tests for the orphan backlog cleanup script.

build_plan is read-only; apply_plan deletes rows (DB) and, when given a
storage manager, S3 objects. Storage is mocked. After an apply, the
detect_orphans detectors should report zero for the cleaned categories.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

from sqlmodel import Session

from app.models.enums import JobFileState, SourceType
from app.models.tables import (
    DataSource,
    JobFile,
    KnowledgeBase,
    KnowledgeBaseDatasourceLink,
    UploadedFile,
    User,
)
from app.services.orphan_detection import (
    find_orphan_datasources,
    find_orphan_job_files,
    find_unselected_uploaded_files,
)
from scripts.cleanup_orphans import apply_plan, build_plan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        file_size=100,
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


def _job_file(db: Session, external_file_id: str) -> JobFile:
    jf = JobFile(
        job_id=uuid.uuid4(),
        external_file_id=external_file_id,
        filename="x.pdf",
        state=JobFileState.INGESTED.value,
    )
    db.add(jf)
    db.commit()
    db.refresh(jf)
    return jf


# ---------------------------------------------------------------------------
# build_plan (read-only)
# ---------------------------------------------------------------------------


def test_build_plan_is_read_only(db: Session, test_user: User) -> None:
    ds = _datasource(db, test_user)  # orphan: no link
    uf = _uploaded_file(db, ds)

    plan = build_plan(db)

    # nothing deleted by planning
    assert db.get(UploadedFile, uf.id) is not None
    assert db.get(DataSource, ds.id) is not None
    assert str(uf.id) in plan.unselected_file_ids
    assert str(ds.id) in plan.orphan_datasource_ids


def test_selected_files_are_not_planned(db: Session, test_user: User) -> None:
    kb = _kb(db, test_user)
    ds = _datasource(db, test_user)
    keep = _uploaded_file(db, ds, "keep.pdf")
    drop = _uploaded_file(db, ds, "drop.pdf")
    _link(db, kb, ds, [keep.id])  # only `keep` is selected

    plan = build_plan(db)

    assert str(drop.id) in plan.unselected_file_ids
    assert str(keep.id) not in plan.unselected_file_ids
    # ds is linked -> not orphan
    assert str(ds.id) not in plan.orphan_datasource_ids


def test_non_uuid_job_files_are_skipped(db: Session) -> None:
    """Moodle/NextCloud native ids must never be planned for deletion."""
    _job_file(db, "19983")  # moodle-style numeric id

    plan = build_plan(db)

    assert plan.orphan_job_file_ids == []


# ---------------------------------------------------------------------------
# apply_plan (DB + S3)
# ---------------------------------------------------------------------------


def test_apply_deletes_rows_and_s3(db: Session, test_user: User) -> None:
    kb = _kb(db, test_user)
    live_ds = _datasource(db, test_user)
    keep = _uploaded_file(db, live_ds, "keep.pdf")
    stale = _uploaded_file(db, live_ds, "stale.pdf")  # deselected, row lingers
    _link(db, kb, live_ds, [keep.id])

    orphan_ds = _datasource(db, test_user)  # no link
    orphan_file = _uploaded_file(db, orphan_ds, "orphan.pdf")

    # a job file pointing at the stale (to-be-deleted) upload -> becomes dangling
    dangling = _job_file(db, str(stale.id))
    # a job file pointing at the kept upload -> must survive
    healthy = _job_file(db, str(keep.id))

    storage = MagicMock()
    storage.delete_file.return_value = True
    storage.delete_datasource_files.return_value = (1, [])

    plan = build_plan(db)
    apply_plan(db, plan, storage)

    # unselected + orphan-datasource files gone, selected file kept
    assert db.get(UploadedFile, stale.id) is None
    assert db.get(UploadedFile, orphan_file.id) is None
    assert db.get(UploadedFile, keep.id) is not None
    # orphan datasource gone, live one kept
    assert db.get(DataSource, orphan_ds.id) is None
    assert db.get(DataSource, live_ds.id) is not None
    # dangling job file gone, healthy one kept
    assert db.get(JobFile, dangling.id) is None
    assert db.get(JobFile, healthy.id) is not None

    # S3: stale + orphan files deleted individually, orphan ds prefix wiped
    assert storage.delete_file.call_count == 2
    storage.delete_datasource_files.assert_called_once()
    assert plan.applied is True


def test_apply_leaves_db_consistent_for_detectors(db: Session, test_user: User) -> None:
    """After cleanup, the orphan detectors report zero for cleaned categories."""
    kb = _kb(db, test_user)
    ds = _datasource(db, test_user)
    stale = _uploaded_file(db, ds, "stale.pdf")
    _link(db, kb, ds, [])  # empty selection -> stale is unselected
    _job_file(db, str(stale.id))

    orphan_ds = _datasource(db, test_user)

    plan = build_plan(db)
    apply_plan(db, plan, storage=None)  # skip-s3 path

    assert find_unselected_uploaded_files(db).count == 0
    assert find_orphan_datasources(db).count == 0
    assert find_orphan_job_files(db).count == 0
    # orphan datasource really gone
    assert db.get(DataSource, orphan_ds.id) is None


def test_skip_s3_touches_no_storage(db: Session, test_user: User) -> None:
    ds = _datasource(db, test_user)  # orphan
    _uploaded_file(db, ds)

    plan = build_plan(db)
    apply_plan(db, plan, storage=None)

    # rows gone, but with storage=None nothing raised and no S3 attempted
    assert plan.s3_objects_deleted == 0
    assert db.get(DataSource, ds.id) is None
