"""Detect orphaned data left behind by partial-failure paths.

Read-only: identifies orphans but never deletes. Callers decide what to
do with the report.

Categories:
- DB: knowledge bases, datasources, uploaded files, jobs, job files
  with no valid parent reference. Usually from a swallowed exception in
  `delete_chatbot` or `update_chatbot_files`.
- S3: objects in the bucket not referenced by any DB row. Usually from
  a failed S3 delete in
  `KnowledgebaseService.delete_knowledgebase_with_validation`.

Vector store (Qdrant via Hayhooks) orphans are out of scope. Hayhooks
has no list-collections endpoint today.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from app.models.enums import JobStatus
from app.models.tables import (
    Chatbot,
    DataSource,
    Job,
    JobFile,
    KnowledgeBase,
    KnowledgeBaseDatasourceLink,
    UploadedFile,
)
from app.services.selection_service import SelectionService

if TYPE_CHECKING:
    from app.core.storage import StorageManager

logger = logging.getLogger(__name__)

# cap on ids/paths kept per report so output stays printable for very
# large leaks. count is still the true total.
_SAMPLE_LIMIT = 100


@dataclass
class OrphanReport:
    """A single category's findings.

    count is the true total. sample_ids is capped at _SAMPLE_LIMIT.
    """

    category: str
    description: str
    count: int = 0
    sample_ids: list[str] = field(default_factory=list)

    def add(self, identifier: str) -> None:
        self.count += 1
        if len(self.sample_ids) < _SAMPLE_LIMIT:
            self.sample_ids.append(identifier)

    def is_empty(self) -> bool:
        return self.count == 0


# ---------------------------------------------------------------------------
# DB-only detectors
# ---------------------------------------------------------------------------


def find_orphan_knowledge_bases(session: Session) -> OrphanReport:
    """KnowledgeBase rows with no Chatbot referencing them.

    Most common cause: delete_chatbot removes the chatbot row first; if
    KB cleanup later raises, the KB stays around forever.
    """
    report = OrphanReport(
        category="db.orphan_knowledge_bases",
        description="KnowledgeBase rows not referenced by any Chatbot",
    )
    referenced_kb_ids: set = set(session.exec(select(Chatbot.knowledge_base_id)).all())
    for kb in session.exec(select(KnowledgeBase)).all():
        if kb.id not in referenced_kb_ids:
            report.add(str(kb.id))
    return report


def find_orphan_datasources(session: Session) -> OrphanReport:
    """DataSource rows not linked to any KnowledgeBase.

    Usually from update_chatbot_files creating a FILE datasource (and
    committing) while the subsequent uploads fail.
    """
    report = OrphanReport(
        category="db.orphan_datasources",
        description="DataSource rows with no KnowledgeBaseDatasourceLink",
    )
    linked_ds_ids: set = set(
        session.exec(select(KnowledgeBaseDatasourceLink.datasource_id)).all()
    )
    for ds in session.exec(select(DataSource)).all():
        if ds.id not in linked_ds_ids:
            report.add(str(ds.id))
    return report


def find_unselected_uploaded_files(session: Session) -> OrphanReport:
    """UploadedFile rows not present in any KB link's selection.

    A file is in active use only if its datasource is linked to a KB
    AND its id appears in that link's selection JSON. Anything else was
    uploaded, then replaced or removed, but the row was never deleted.
    """
    report = OrphanReport(
        category="db.unselected_uploaded_files",
        description=(
            "UploadedFile rows whose id is not referenced by any "
            "KnowledgeBaseDatasourceLink selection"
        ),
    )
    selected_file_ids: set = set()
    for link in session.exec(select(KnowledgeBaseDatasourceLink)).all():
        selections = SelectionService.parse_selections(link.selection)
        for file_uuid in SelectionService.extract_file_ids(selections):
            selected_file_ids.add(file_uuid)
    for uploaded in session.exec(select(UploadedFile)).all():
        if uploaded.id not in selected_file_ids:
            report.add(str(uploaded.id))
    return report


def find_stuck_jobs(session: Session) -> OrphanReport:
    """Jobs in PENDING/RUNNING whose KB no longer exists.

    Caused by a chatbot/KB delete during an in-flight indexing job. The
    KB row is gone, worker progress updates have nowhere to land, and
    the job stays "active" forever to the cancel/scheduler paths.
    """
    report = OrphanReport(
        category="db.stuck_jobs_missing_kb",
        description=(
            "Jobs in PENDING or RUNNING status whose knowledge_base_id no longer exists"
        ),
    )
    kb_ids: set = set(session.exec(select(KnowledgeBase.id)).all())
    active_statuses = (JobStatus.PENDING.value, JobStatus.RUNNING.value)
    stmt = select(Job).where(
        Job.status.in_(active_statuses),  # type: ignore[attr-defined]
        Job.knowledge_base_id.is_not(None),  # type: ignore[union-attr]
    )
    for job in session.exec(stmt).all():
        if job.knowledge_base_id not in kb_ids:
            report.add(str(job.id))
    return report


def find_orphan_job_files(session: Session) -> OrphanReport:
    """JobFile rows whose UUID external_file_id is not a real UploadedFile id.

    JobFile.external_file_id is a generic string: for FILE-datasource
    ingestion it holds the UploadedFile UUID, for Moodle/NextCloud it
    holds the source-system's native id (e.g. "19983"). Only UUID-shaped
    ids can be reconciled here. Non-UUIDs are skipped to avoid swamping
    the report with Moodle job files that are working as intended.
    """
    report = OrphanReport(
        category="db.orphan_job_files",
        description=(
            "JobFile rows whose UUID external_file_id does not match any "
            "UploadedFile.id. Non-UUID ids are skipped because those belong "
            "to Moodle/NextCloud syncs, not local uploads"
        ),
    )
    uploaded_ids: set[str] = {
        str(uid) for uid in session.exec(select(UploadedFile.id)).all()
    }
    for jf in session.exec(select(JobFile)).all():
        try:
            uuid.UUID(jf.external_file_id)
        except (ValueError, AttributeError):
            continue
        if jf.external_file_id not in uploaded_ids:
            report.add(str(jf.id))
    return report


# ---------------------------------------------------------------------------
# S3 detectors
# ---------------------------------------------------------------------------


def _iter_known_s3_paths(session: Session) -> tuple[set[str], set[str], set[str]]:
    """Build the set of S3 paths the DB expects to exist.

    Returns (file_paths, avatar_paths, datasource_ids). datasource_ids
    is used to recognise which datasources/<id>/ prefixes are live.
    """
    file_paths: set[str] = {
        sp for sp in session.exec(select(UploadedFile.storage_path)).all() if sp
    }
    avatar_paths: set[str] = {
        ap for ap in session.exec(select(Chatbot.avatar_storage_path)).all() if ap
    }
    datasource_ids: set[str] = {
        str(ds_id) for ds_id in session.exec(select(DataSource.id)).all()
    }
    return file_paths, avatar_paths, datasource_ids


def _classify_s3_object(
    object_name: str,
    file_paths: set[str],
    avatar_paths: set[str],
    datasource_ids: set[str],
) -> str | None:
    """Return the orphan category for object_name or None if known.

    Path layout (see app.core.storage):
    - {email}/{namespace}/datasources/{ds_id}/uploads/{filename}: FILE
      datasources, tracked in UploadedFile
    - {email}/{namespace}/datasources/{ds_id}/<other>/...: Moodle /
      NextCloud sync caches, not in UploadedFile
    - {email}/{namespace}/chatbots/{chatbot_id}/avatar/{filename}: avatars

    For non-uploads/ subpaths under a live datasource we only verify
    the datasource itself still exists (Moodle file ids are external
    numeric ids stored only in the source system).
    """
    parts = object_name.split("/")
    # need at least: email / namespace / kind / id / ... / filename
    if len(parts) < 5:
        return "s3.unknown_path"

    kind = parts[2]
    if kind == "datasources":
        ds_id = parts[3]
        if ds_id not in datasource_ids:
            return "s3.orphan_datasource_dir"
        subdir = parts[4]
        if subdir == "uploads":
            # uploads/ is the only subpath tracked per-file in DB
            if object_name in file_paths:
                return None
            return "s3.orphan_uploaded_file"
        # Moodle/NextCloud sync cache; existence managed externally
        return None
    if kind == "chatbots":
        # avatar_storage_path already pins the live ones
        if object_name in avatar_paths:
            return None
        return "s3.orphan_avatar"
    return "s3.unknown_path"


def find_s3_orphans(
    session: Session, storage: StorageManager
) -> dict[str, OrphanReport]:
    """Walk the bucket once and classify each object against DB references.

    Returns four reports keyed by category name.
    """
    file_paths, avatar_paths, datasource_ids = _iter_known_s3_paths(session)

    reports: dict[str, OrphanReport] = {
        "s3.orphan_datasource_dir": OrphanReport(
            category="s3.orphan_datasource_dir",
            description=(
                "S3 objects under datasources/{id}/ where {id} is not a live DataSource"
            ),
        ),
        "s3.orphan_uploaded_file": OrphanReport(
            category="s3.orphan_uploaded_file",
            description=(
                "S3 objects under a live datasource but not referenced by "
                "any UploadedFile.storage_path"
            ),
        ),
        "s3.orphan_avatar": OrphanReport(
            category="s3.orphan_avatar",
            description=(
                "Avatar objects not referenced by any Chatbot.avatar_storage_path"
            ),
        ),
        "s3.unknown_path": OrphanReport(
            category="s3.unknown_path",
            description=(
                "S3 objects whose path doesn't match the datasources/ or "
                "chatbots/ layout. Surface for manual review."
            ),
        ),
    }

    # empty prefix = whole bucket
    for object_name in storage.list_files(prefix="", recursive=True):
        category = _classify_s3_object(
            object_name, file_paths, avatar_paths, datasource_ids
        )
        if category is None:
            continue
        reports[category].add(object_name)
    return reports


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def detect_all(
    session: Session, storage: StorageManager | None = None
) -> list[OrphanReport]:
    """Run every detector and return a flat list of reports.

    Pass storage=None to skip S3 detection; DB-only checks still run.
    """
    reports: list[OrphanReport] = [
        find_orphan_knowledge_bases(session),
        find_orphan_datasources(session),
        find_unselected_uploaded_files(session),
        find_stuck_jobs(session),
        find_orphan_job_files(session),
    ]
    if storage is not None:
        try:
            reports.extend(find_s3_orphans(session, storage).values())
        except Exception as exc:
            logger.error("S3 orphan detection failed: %s", exc)
    return reports
