"""Delete orphaned backlog data left by the historical file-update leak.


DRY-RUN BY DEFAULT. Nothing is deleted unless ``--apply`` is passed.

Deletion order is dependency-safe:
1. unselected ``UploadedFile`` rows (+ their S3 objects)
2. orphan ``DataSource`` rows (their configs + S3 prefix)
3. dangling ``JobFile`` rows (no S3) computed against what survives 1+2

DB deletes commit in one transaction; S3 deletes run best-effort *after* the
commit, so a storage error can never leave the DB half-cleaned.

Usage (from api/):
    uv run python -m scripts.cleanup_orphans              # dry-run report
    uv run python -m scripts.cleanup_orphans --apply      # actually delete
    uv run python -m scripts.cleanup_orphans --apply --skip-s3
"""

from __future__ import annotations

import argparse
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from app.core.db import engine
from app.core.storage import StorageManager
from app.models.tables import (
    DataSource,
    JobFile,
    KnowledgeBaseDatasourceLink,
    UploadedFile,
)
from app.services.selection_service import SelectionService

if TYPE_CHECKING:
    from app.core.storage import StorageManager as _StorageManager


@dataclass
class CleanupPlan:
    """What the run will delete, and what it actually deleted on --apply."""

    unselected_file_ids: list[str] = field(default_factory=list)
    unselected_s3_paths: list[str] = field(default_factory=list)
    unselected_bytes: int = 0

    orphan_datasource_ids: list[str] = field(default_factory=list)
    orphan_datasource_prefixes: list[tuple[str, str]] = field(default_factory=list)

    orphan_job_file_ids: list[str] = field(default_factory=list)

    s3_objects_deleted: int = 0
    s3_errors: list[str] = field(default_factory=list)
    applied: bool = False


def _is_uuid(value: str | None) -> bool:
    try:
        uuid.UUID(value)  # type: ignore[arg-type]
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def build_plan(session: Session) -> CleanupPlan:
    """Compute every row/object the cleanup would remove. Read-only."""
    plan = CleanupPlan()

    # --- selections: which uploaded files are still in active use ----------
    selected_ids: set[uuid.UUID] = set()
    for link in session.exec(select(KnowledgeBaseDatasourceLink)).all():
        selections = SelectionService.parse_selections(link.selection)
        for fid in SelectionService.extract_file_ids(selections):
            selected_ids.add(fid)

    all_uploaded = list(session.exec(select(UploadedFile)).all())
    surviving_upload_id_strs: set[str] = set()
    for uf in all_uploaded:
        if uf.id in selected_ids:
            surviving_upload_id_strs.add(str(uf.id))
            continue
        plan.unselected_file_ids.append(str(uf.id))
        if uf.storage_path:
            plan.unselected_s3_paths.append(uf.storage_path)
        plan.unselected_bytes += uf.file_size or 0

    # --- datasources with no KB link ---------------------------------------
    linked_ds_ids: set[uuid.UUID] = set(
        session.exec(select(KnowledgeBaseDatasourceLink.datasource_id)).all()
    )
    for ds in session.exec(select(DataSource)).all():
        if ds.id in linked_ds_ids:
            continue
        plan.orphan_datasource_ids.append(str(ds.id))
        owner_email = ds.owner.email if ds.owner else None
        if owner_email:
            plan.orphan_datasource_prefixes.append((owner_email, str(ds.id)))

    # --- JobFile rows dangling against the POST-cleanup upload set ----------
    # a UUID external_file_id that won't match any surviving UploadedFile.
    for jf in session.exec(select(JobFile)).all():
        if not _is_uuid(jf.external_file_id):
            continue  # Moodle/NextCloud native ids, working as intended
        if jf.external_file_id not in surviving_upload_id_strs:
            plan.orphan_job_file_ids.append(str(jf.id))

    return plan


def apply_plan(
    session: Session, plan: CleanupPlan, storage: _StorageManager | None
) -> None:
    """Execute the plan: DB deletes in one transaction, then S3 best-effort."""
    # 1. unselected uploaded files
    for fid in plan.unselected_file_ids:
        uf = session.get(UploadedFile, uuid.UUID(fid))
        if uf is not None:
            session.delete(uf)
    session.flush()

    # 2. orphan datasources: configs first (moodle_config cascades to courses),
    #    then any residual files, then the datasource row.
    for ds_id in plan.orphan_datasource_ids:
        ds = session.get(DataSource, uuid.UUID(ds_id))
        if ds is None:
            continue
        if ds.moodle_config is not None:
            session.delete(ds.moodle_config)
        if ds.nextcloud_config is not None:
            session.delete(ds.nextcloud_config)
        for residual in session.exec(
            select(UploadedFile).where(UploadedFile.datasource_id == ds.id)
        ).all():
            session.delete(residual)
        session.flush()
        session.delete(ds)

    # 3. dangling job files (no S3 side effect)
    for jf_id in plan.orphan_job_file_ids:
        jf = session.get(JobFile, uuid.UUID(jf_id))
        if jf is not None:
            session.delete(jf)

    session.commit()
    plan.applied = True

    # S3 cleanup after the commit so a storage error can't half-undo the DB work
    if storage is None:
        return
    for path in plan.unselected_s3_paths:
        try:
            if storage.delete_file(path):
                plan.s3_objects_deleted += 1
        except Exception as e:  # noqa: BLE001 - best-effort sweep
            plan.s3_errors.append(f"{path}: {e}")
    for owner_email, ds_id in plan.orphan_datasource_prefixes:
        try:
            deleted, errors = storage.delete_datasource_files(
                user_email=owner_email, datasource_id=ds_id
            )
            plan.s3_objects_deleted += deleted
            plan.s3_errors.extend(errors)
        except Exception as e:  # noqa: BLE001
            plan.s3_errors.append(f"datasources/{ds_id}/: {e}")


def _print_report(plan: CleanupPlan, *, applied: bool, skip_s3: bool) -> None:
    verb = "Deleted" if applied else "Would delete"
    mib = plan.unselected_bytes / (1024 * 1024)
    print(f"\nOrphan cleanup ({'APPLY' if applied else 'DRY-RUN'})\n")
    print(f"  {verb} {len(plan.unselected_file_ids)} unselected uploaded file row(s)")
    print(
        f"     S3 objects: {len(plan.unselected_s3_paths)} "
        f"(~{mib:.1f} MiB tracked){' [skipped]' if skip_s3 else ''}"
    )
    print(f"  {verb} {len(plan.orphan_datasource_ids)} orphan datasource row(s)")
    print(
        f"     S3 prefixes wiped: {len(plan.orphan_datasource_prefixes)}"
        f"{' [skipped]' if skip_s3 else ''}"
    )
    print(f"  {verb} {len(plan.orphan_job_file_ids)} dangling job file row(s) (no S3)")
    if applied and not skip_s3:
        print(f"\n  S3 objects actually deleted: {plan.s3_objects_deleted}")
        if plan.s3_errors:
            print(f"  S3 errors: {len(plan.s3_errors)} (first 5)")
            for err in plan.s3_errors[:5]:
                print(f"     - {err}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete orphaned backlog data (dry-run unless --apply)."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually delete (default: dry-run)"
    )
    parser.add_argument(
        "--skip-s3",
        action="store_true",
        help="Delete DB rows only; leave S3 objects untouched",
    )
    args = parser.parse_args()

    storage = None if args.skip_s3 else StorageManager()
    with Session(engine) as session:
        plan = build_plan(session)
        if args.apply:
            apply_plan(session, plan, storage)

    _print_report(plan, applied=args.apply, skip_s3=args.skip_s3)
    if not args.apply:
        print("Dry-run only. Re-run with --apply to delete.\n")


if __name__ == "__main__":
    main()
