"""Tests for orphan detection.

DB detectors run against the in-memory SQLite from conftest. The S3
classifier is unit-tested without touching MinIO.
"""

from __future__ import annotations

import json
import uuid

from sqlmodel import Session

from app.models.enums import (
    ChatbotPersonaType,
    JobFileState,
    JobStatus,
    JobType,
    SourceType,
)
from app.models.tables import (
    Chatbot,
    DataSource,
    Job,
    JobFile,
    KnowledgeBase,
    KnowledgeBaseDatasourceLink,
    UploadedFile,
    User,
)
from app.services.orphan_detection import (
    _classify_s3_object,
    detect_all,
    find_orphan_datasources,
    find_orphan_job_files,
    find_orphan_knowledge_bases,
    find_stuck_jobs,
    find_unselected_uploaded_files,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kb(db: Session, user: User, name: str = "kb") -> KnowledgeBase:
    kb = KnowledgeBase(name=name, user_id=user.id)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


def _make_chatbot(db: Session, user: User, kb: KnowledgeBase) -> Chatbot:
    chatbot = Chatbot(
        name="cb",
        owner_id=user.id,
        knowledge_base_id=kb.id,
        personaType=ChatbotPersonaType.TEACHER.value,
    )
    db.add(chatbot)
    db.commit()
    db.refresh(chatbot)
    return chatbot


def _make_datasource(db: Session, user: User) -> DataSource:
    ds = DataSource(name="ds", source_type=SourceType.FILE.value, owner_id=user.id)
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def _link(
    db: Session,
    kb: KnowledgeBase,
    ds: DataSource,
    selected_file_ids: list[uuid.UUID] | None = None,
) -> KnowledgeBaseDatasourceLink:
    selection_payload = (
        json.dumps([f"file:{fid}" for fid in selected_file_ids])
        if selected_file_ids
        else ""
    )
    link = KnowledgeBaseDatasourceLink(
        knowledge_base_id=kb.id,
        datasource_id=ds.id,
        selection=selection_payload,
    )
    db.add(link)
    db.commit()
    return link


def _make_uploaded_file(db: Session, ds: DataSource) -> UploadedFile:
    uf = UploadedFile(
        datasource_id=ds.id,
        original_filename="x.pdf",
        stored_filename="x.pdf",
        file_size=10,
        mime_type="application/pdf",
        file_hash="h",
        storage_path=f"u@e/ns/datasources/{ds.id}/uploads/x.pdf",
    )
    db.add(uf)
    db.commit()
    db.refresh(uf)
    return uf


# ---------------------------------------------------------------------------
# DB detector tests
# ---------------------------------------------------------------------------


def test_empty_db_has_no_orphans(db: Session) -> None:
    reports = detect_all(db, storage=None)
    assert all(r.is_empty() for r in reports), [r for r in reports if not r.is_empty()]


def test_kb_with_chatbot_is_not_orphan(db: Session, test_user: User) -> None:
    kb = _make_kb(db, test_user)
    _make_chatbot(db, test_user, kb)
    assert find_orphan_knowledge_bases(db).is_empty()


def test_kb_without_chatbot_is_orphan(db: Session, test_user: User) -> None:
    kb = _make_kb(db, test_user, name="dangling")
    report = find_orphan_knowledge_bases(db)
    assert report.count == 1
    assert str(kb.id) in report.sample_ids


def test_datasource_linked_to_kb_is_not_orphan(db: Session, test_user: User) -> None:
    kb = _make_kb(db, test_user)
    _make_chatbot(db, test_user, kb)
    ds = _make_datasource(db, test_user)
    _link(db, kb, ds)
    assert find_orphan_datasources(db).is_empty()


def test_datasource_with_no_link_is_orphan(db: Session, test_user: User) -> None:
    ds = _make_datasource(db, test_user)
    report = find_orphan_datasources(db)
    assert report.count == 1
    assert str(ds.id) in report.sample_ids


def test_unselected_uploaded_file_is_orphan(db: Session, test_user: User) -> None:
    """File in a live datasource but not in any KB selection is dead weight."""
    kb = _make_kb(db, test_user)
    _make_chatbot(db, test_user, kb)
    ds = _make_datasource(db, test_user)
    selected = _make_uploaded_file(db, ds)
    unselected = _make_uploaded_file(db, ds)
    _link(db, kb, ds, selected_file_ids=[selected.id])

    report = find_unselected_uploaded_files(db)
    assert report.count == 1
    assert str(unselected.id) in report.sample_ids
    assert str(selected.id) not in report.sample_ids


def test_stuck_pending_job_with_missing_kb(db: Session, test_user: User) -> None:
    missing_kb_id = uuid.uuid4()
    job = Job(
        job_type=JobType.INGESTION.value,
        status=JobStatus.PENDING.value,
        user_id=test_user.id,
        knowledge_base_id=missing_kb_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    report = find_stuck_jobs(db)
    assert report.count == 1
    assert str(job.id) in report.sample_ids


def test_completed_job_is_not_stuck(db: Session, test_user: User) -> None:
    """Only PENDING/RUNNING count as stuck; finalised states are fine."""
    job = Job(
        job_type=JobType.INGESTION.value,
        status=JobStatus.COMPLETED.value,
        user_id=test_user.id,
        knowledge_base_id=uuid.uuid4(),
    )
    db.add(job)
    db.commit()
    assert find_stuck_jobs(db).is_empty()


def test_orphan_job_file(db: Session, test_user: User) -> None:
    job = Job(
        job_type=JobType.INGESTION.value,
        status=JobStatus.COMPLETED.value,
        user_id=test_user.id,
        knowledge_base_id=uuid.uuid4(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    jf = JobFile(
        job_id=job.id,
        external_file_id=str(uuid.uuid4()),  # references nothing
        filename="ghost.pdf",
        state=JobFileState.PENDING.value,
    )
    db.add(jf)
    db.commit()

    report = find_orphan_job_files(db)
    assert report.count == 1
    assert str(jf.id) in report.sample_ids


def test_moodle_jobfile_external_id_is_not_orphan(db: Session, test_user: User) -> None:
    """Moodle ingestion stores source-system ids (e.g. "19983") in
    external_file_id. Non-UUIDs are skipped to avoid false positives."""
    job = Job(
        job_type=JobType.INGESTION.value,
        status=JobStatus.COMPLETED.value,
        user_id=test_user.id,
        knowledge_base_id=uuid.uuid4(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    jf = JobFile(
        job_id=job.id,
        external_file_id="19983",  # Moodle id, not a UUID
        filename="quiz.h5p",
        state=JobFileState.PENDING.value,
    )
    db.add(jf)
    db.commit()

    assert find_orphan_job_files(db).is_empty()


# ---------------------------------------------------------------------------
# S3 classifier tests (no MinIO required)
# ---------------------------------------------------------------------------


def test_classifier_recognises_known_file() -> None:
    ds_id = str(uuid.uuid4())
    path = f"u@e.com/ns/datasources/{ds_id}/uploads/x.pdf"
    assert (
        _classify_s3_object(
            path,
            file_paths={path},
            avatar_paths=set(),
            datasource_ids={ds_id},
        )
        is None
    )


def test_classifier_flags_unknown_file_in_live_datasource() -> None:
    ds_id = str(uuid.uuid4())
    path = f"u@e.com/ns/datasources/{ds_id}/uploads/leaked.pdf"
    assert (
        _classify_s3_object(
            path,
            file_paths=set(),
            avatar_paths=set(),
            datasource_ids={ds_id},
        )
        == "s3.orphan_uploaded_file"
    )


def test_classifier_accepts_moodle_subpath_under_live_datasource() -> None:
    """Moodle sync caches under datasources/{id}/moodle/, not tracked in
    UploadedFile so we only verify the datasource is alive."""
    ds_id = str(uuid.uuid4())
    path = (
        f"u@e.com/ns/datasources/{ds_id}/moodle/"
        "https_x.eu/course_11/section_1/activity_296/file_19983_x.docx"
    )
    assert (
        _classify_s3_object(
            path,
            file_paths=set(),
            avatar_paths=set(),
            datasource_ids={ds_id},
        )
        is None
    )


def test_classifier_flags_moodle_subpath_under_dead_datasource() -> None:
    """Dead datasource means the whole prefix is orphaned."""
    path = (
        "u@e.com/ns/datasources/00000000-0000-0000-0000-000000000000/"
        "moodle/https_x.eu/course_1/file_1.pdf"
    )
    assert (
        _classify_s3_object(
            path, file_paths=set(), avatar_paths=set(), datasource_ids=set()
        )
        == "s3.orphan_datasource_dir"
    )


def test_classifier_flags_dead_datasource_dir() -> None:
    path = "u@e.com/ns/datasources/00000000-0000-0000-0000-000000000000/uploads/x.pdf"
    assert (
        _classify_s3_object(
            path, file_paths=set(), avatar_paths=set(), datasource_ids=set()
        )
        == "s3.orphan_datasource_dir"
    )


def test_classifier_flags_orphan_avatar() -> None:
    cb_id = uuid.uuid4()
    path = f"u@e.com/ns/chatbots/{cb_id}/avatar/old.png"
    assert (
        _classify_s3_object(
            path, file_paths=set(), avatar_paths=set(), datasource_ids=set()
        )
        == "s3.orphan_avatar"
    )


def test_classifier_recognises_known_avatar() -> None:
    cb_id = uuid.uuid4()
    path = f"u@e.com/ns/chatbots/{cb_id}/avatar/current.png"
    assert (
        _classify_s3_object(
            path, file_paths=set(), avatar_paths={path}, datasource_ids=set()
        )
        is None
    )


def test_classifier_flags_unknown_layout() -> None:
    assert (
        _classify_s3_object(
            "u@e.com/ns/wat/something/else.bin",
            file_paths=set(),
            avatar_paths=set(),
            datasource_ids=set(),
        )
        == "s3.unknown_path"
    )


def test_classifier_flags_short_path() -> None:
    assert (
        _classify_s3_object(
            "too/short",
            file_paths=set(),
            avatar_paths=set(),
            datasource_ids=set(),
        )
        == "s3.unknown_path"
    )


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def test_detect_all_skips_s3_when_storage_is_none(db: Session, test_user: User) -> None:
    _make_kb(db, test_user, name="dangling")
    reports = detect_all(db, storage=None)
    categories = {r.category for r in reports if not r.is_empty()}
    assert "db.orphan_knowledge_bases" in categories
    # no S3 reports at all
    assert not any(r.category.startswith("s3.") for r in reports)


def test_detect_all_continues_when_s3_listing_raises(
    db: Session, test_user: User
) -> None:
    """If bucket listing fails, DB report still comes back."""
    _make_kb(db, test_user, name="dangling")

    class _BoomStorage:
        def list_files(
            self, prefix: str, recursive: bool = True
        ) -> list[str]:  # pragma: no cover - argument signature only
            raise RuntimeError("minio down")

    reports = detect_all(db, storage=_BoomStorage())  # type: ignore[arg-type]
    categories = {r.category for r in reports if not r.is_empty()}
    assert "db.orphan_knowledge_bases" in categories
