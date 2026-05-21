from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from app.models.enums import (
    DataSourceSyncStatus,
    JobFileState,
    JobStatus,
    JobType,
    KnowledgeBaseStatus,
    SourceType,
)
from app.models.tables import (
    DataSource,
    JobFile,
    KnowledgeBase,
    User,
)
from app.repositories.job import JobRepository


class TestJobLifecycle:
    def test_create_job_sets_pending_status(self, db: Session, test_user: User) -> None:
        job_repo = JobRepository(db)

        job = job_repo.create_job(
            job_type=JobType.INGESTION,
            user_id=test_user.id,
        )

        assert job.status == JobStatus.PENDING.value
        assert job.started_at is None
        assert job.completed_at is None

    def test_start_job_sets_running_status(self, db: Session, test_user: User) -> None:
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)

        result = job_repo.start_job(job.id)

        assert result is not None
        assert result.status == JobStatus.RUNNING.value
        assert result.started_at is not None

    def test_complete_job_sets_completed_status(
        self, db: Session, test_user: User
    ) -> None:
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        result = job_repo.complete_job(job.id, result_summary={"docs_indexed": 42})

        assert result is not None
        assert result.status == JobStatus.COMPLETED.value
        assert result.completed_at is not None
        assert result.result_summary is not None
        assert "42" in result.result_summary

    def test_fail_job_captures_error(self, db: Session, test_user: User) -> None:
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        result = job_repo.fail_job(
            job.id,
            error_message="Connection timeout",
            error_details="Traceback...",
        )

        assert result is not None
        assert result.status == JobStatus.FAILED.value
        assert result.error_message == "Connection timeout"
        assert result.error_details == "Traceback..."

    def test_complete_job_without_start(self, db: Session, test_user: User) -> None:
        """complete_job on a never-started job (message redelivery, races)."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.METADATA_SYNC, user_id=test_user.id)

        result = job_repo.complete_job(job.id)

        # completes without started_at
        assert result is not None
        assert result.status == JobStatus.COMPLETED.value
        assert result.started_at is None


class TestStalledJobDetection:
    def test_stale_progress_marks_running_job_stalled(
        self, db: Session, test_user: User
    ) -> None:
        """RUNNING job past the stale window gets reaped and its KB reset."""
        kb = KnowledgeBase(
            name="Test KB",
            user_id=test_user.id,
            status=KnowledgeBaseStatus.PROCESSING.value,
        )
        db.add(kb)
        db.commit()

        job_repo = JobRepository(db)
        job = job_repo.create_job(
            job_type=JobType.INGESTION,
            user_id=test_user.id,
            knowledge_base_id=kb.id,
        )
        job_repo.start_job(job.id)

        # started 2h ago, last progress 45m ago, stale window 30m
        now = datetime.now(UTC)
        job.started_at = now - timedelta(hours=2)
        job.progress_updated_at = now - timedelta(minutes=45)
        db.commit()

        stalled = job_repo.mark_stalled_jobs(
            running_stale_minutes=30, running_absolute_minutes=360
        )

        assert len(stalled) == 1
        assert stalled[0].status == JobStatus.STALLED.value
        assert "stalled" in (stalled[0].error_message or "").lower()

        db.refresh(kb)
        assert kb.status == KnowledgeBaseStatus.ERROR.value
        assert "stalled" in (kb.last_sync_error or "").lower()

    def test_progressing_job_within_stale_window_is_not_reaped(
        self, db: Session, test_user: User
    ) -> None:
        """Long-running job that keeps publishing progress must survive."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        now = datetime.now(UTC)
        job.started_at = now - timedelta(hours=2)
        job.progress_updated_at = now - timedelta(minutes=5)  # recent progress
        db.commit()

        stalled = job_repo.mark_stalled_jobs(
            running_stale_minutes=30, running_absolute_minutes=360
        )

        assert len(stalled) == 0

    def test_absolute_timeout_reaps_progressing_job(
        self, db: Session, test_user: User
    ) -> None:
        """Absolute ceiling kills even jobs that keep reporting progress."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        now = datetime.now(UTC)
        job.started_at = now - timedelta(hours=7)
        job.progress_updated_at = now - timedelta(minutes=1)  # still ticking
        db.commit()

        stalled = job_repo.mark_stalled_jobs(
            running_stale_minutes=30, running_absolute_minutes=360
        )

        assert len(stalled) == 1
        assert "absolute" in (stalled[0].error_message or "").lower()

    def test_datasource_status_reset_on_stall(
        self, db: Session, test_user: User
    ) -> None:
        """Datasource sync stall resets the datasource so the user can retry."""
        ds = DataSource(
            name="Test DS",
            source_type=SourceType.MOODLE,
            owner_id=test_user.id,
            sync_status=DataSourceSyncStatus.PROCESSING.value,
        )
        db.add(ds)
        db.commit()

        job_repo = JobRepository(db)
        job = job_repo.create_job(
            job_type=JobType.METADATA_SYNC,
            user_id=test_user.id,
            datasource_id=ds.id,
        )
        job_repo.start_job(job.id)

        now = datetime.now(UTC)
        job.started_at = now - timedelta(hours=2)
        job.progress_updated_at = now - timedelta(hours=1)
        db.commit()

        stalled = job_repo.mark_stalled_jobs(
            running_stale_minutes=30, running_absolute_minutes=360
        )

        assert len(stalled) == 1
        db.refresh(ds)
        assert ds.sync_status == DataSourceSyncStatus.ERROR.value
        assert ds.last_sync_error is not None

    def test_mark_stalled_pending_jobs(self, db: Session, test_user: User) -> None:
        """PENDING jobs never picked up also get marked stalled."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(
            job_type=JobType.CONTENT_SYNC,
            user_id=test_user.id,
        )
        job.created_at = datetime.now(UTC) - timedelta(hours=3)
        db.commit()

        stalled = job_repo.mark_stalled_jobs(pending_timeout_minutes=120)

        assert len(stalled) == 1
        assert stalled[0].status == JobStatus.STALLED.value

    def test_mark_stalled_ignores_recent_jobs(
        self, db: Session, test_user: User
    ) -> None:
        """Recently started jobs are not stalled."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        job.started_at = datetime.now(UTC) - timedelta(minutes=10)
        job.progress_updated_at = job.started_at
        db.commit()

        stalled = job_repo.mark_stalled_jobs(
            running_stale_minutes=30, running_absolute_minutes=360
        )

        assert len(stalled) == 0

    def test_absolute_timeout_takes_priority_over_stale_reason(
        self, db: Session, test_user: User
    ) -> None:
        """When both conditions hit, the absolute reason wins in the message."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        now = datetime.now(UTC)
        # 7h ago, past the 6h absolute ceiling
        job.started_at = now - timedelta(hours=7)
        # 2h ago, also past the 30m stale window
        job.progress_updated_at = now - timedelta(hours=2)
        db.commit()

        stalled = job_repo.mark_stalled_jobs(
            running_stale_minutes=30, running_absolute_minutes=360
        )

        assert len(stalled) == 1
        reason = (stalled[0].error_message or "").lower()
        assert "absolute" in reason
        assert "no progress since" not in reason

    def test_mark_all_running_as_stalled_reaps_everything(
        self, db: Session, test_user: User
    ) -> None:
        """Startup reap kills every RUNNING/PENDING job regardless of times."""
        job_repo = JobRepository(db)

        # fresh running job, would normally NOT be stalled
        running = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(running.id)

        pending = job_repo.create_job(
            job_type=JobType.CONTENT_SYNC, user_id=test_user.id
        )

        # completed job must NOT be touched
        completed = job_repo.create_job(
            job_type=JobType.METADATA_SYNC, user_id=test_user.id
        )
        job_repo.start_job(completed.id)
        job_repo.complete_job(completed.id)

        stalled = job_repo.mark_all_running_as_stalled()

        assert {j.id for j in stalled} == {running.id, pending.id}

        db.refresh(running)
        db.refresh(pending)
        db.refresh(completed)
        assert running.status == JobStatus.STALLED.value
        assert pending.status == JobStatus.STALLED.value
        assert completed.status == JobStatus.COMPLETED.value


class TestConcurrentJobDetection:
    def test_get_active_for_knowledge_base(self, db: Session, test_user: User) -> None:
        """Bug scenario: user triggers reindex twice, creating duplicates."""
        kb = KnowledgeBase(name="Test KB", user_id=test_user.id)
        db.add(kb)
        db.commit()

        job_repo = JobRepository(db)

        job1 = job_repo.create_job(
            job_type=JobType.INGESTION,
            user_id=test_user.id,
            knowledge_base_id=kb.id,
        )
        job_repo.start_job(job1.id)

        active = job_repo.get_active_for_knowledge_base(kb.id)
        assert active is not None
        assert active.id == job1.id

    def test_no_active_job_for_completed_jobs(
        self, db: Session, test_user: User
    ) -> None:
        """Completed jobs don't block new job creation."""
        kb = KnowledgeBase(name="Test KB", user_id=test_user.id)
        db.add(kb)
        db.commit()

        job_repo = JobRepository(db)

        job = job_repo.create_job(
            job_type=JobType.INGESTION,
            user_id=test_user.id,
            knowledge_base_id=kb.id,
        )
        job_repo.start_job(job.id)
        job_repo.complete_job(job.id)

        active = job_repo.get_active_for_knowledge_base(kb.id)
        assert active is None

    def test_get_latest_returns_old_completed_job(
        self, db: Session, test_user: User
    ) -> None:
        """Returns the most recent KB job regardless of when it finished.

        Regression guard for the old 5-minute cutoff that hid failed jobs
        after any API restart. Failure persistence depends on this.
        """
        kb = KnowledgeBase(name="Test KB", user_id=test_user.id)
        db.add(kb)
        db.commit()

        job_repo = JobRepository(db)
        job = job_repo.create_job(
            job_type=JobType.INGESTION,
            user_id=test_user.id,
            knowledge_base_id=kb.id,
        )
        job_repo.start_job(job.id)
        job_repo.complete_job(job.id)

        # past the old 5-min window so a cutoff-based impl would drop it
        long_ago = datetime.now(UTC) - timedelta(days=7)
        job.completed_at = long_ago
        db.commit()

        latest = job_repo.get_latest_for_knowledge_base(kb.id)
        assert latest is not None
        assert latest.id == job.id


class TestJobProgress:
    def test_update_progress_rejects_positional_args(
        self, db: Session, test_user: User
    ) -> None:
        """update_progress is keyword-only after job_id. Guards old callers
        that passed current/total positionally."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        with pytest.raises(TypeError):
            job_repo.update_progress(job.id, "Processing documents...")  # type: ignore[misc]

    def test_aggregate_progress_update_bumps_timestamp(
        self, db: Session, test_user: User
    ) -> None:
        """Aggregate progress (no file) still bumps progress_updated_at."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        # stored value round-trips as naive, compare in naive UTC
        baseline = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None)
        job.progress_updated_at = baseline
        db.commit()

        result = job_repo.update_progress(
            job.id, message="Connected to processing service", total_files=10
        )

        assert result is not None
        assert result.progress_message == "Connected to processing service"
        assert result.progress_total == 10
        assert result.progress_updated_at is not None
        assert result.progress_updated_at > baseline

    def test_per_file_progress_upserts_and_counts_terminal_states(
        self, db: Session, test_user: User
    ) -> None:
        """Per-file updates upsert JobFile rows. progress_current counts
        only terminal states (INGESTED/SKIPPED/FAILED)."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        # file 1: downloading -> ingested (terminal)
        job_repo.update_progress(
            job.id,
            file={
                "external_file_id": "17652",
                "filename": "Test_9Tips.h5p",
                "state": JobFileState.DOWNLOADING.value,
            },
        )
        job_repo.update_progress(
            job.id,
            file={
                "external_file_id": "17652",
                "filename": "Test_9Tips.h5p",
                "state": JobFileState.INGESTED.value,
            },
        )

        # file 2: failed (terminal). error_detail is the verbose payload
        # kept alongside the short error_message for admin triage.
        job_repo.update_progress(
            job.id,
            file={
                "external_file_id": "18932",
                "filename": "Thumb_ESPR.png",
                "state": JobFileState.FAILED.value,
                "error_message": "Could not process file",
                "error_detail": "Thumb_ESPR.png: docling rejected PNG (no OCR)",
            },
        )

        # file 3: still ingesting (not terminal)
        job_repo.update_progress(
            job.id,
            file={
                "external_file_id": "19397",
                "filename": "Timeline_ESPR.png",
                "state": JobFileState.INGESTING.value,
            },
        )

        job_files = list(db.exec(select(JobFile).where(JobFile.job_id == job.id)))
        assert len(job_files) == 3
        by_id = {jf.external_file_id: jf for jf in job_files}
        assert by_id["17652"].state == JobFileState.INGESTED.value
        assert by_id["18932"].state == JobFileState.FAILED.value
        assert by_id["18932"].error_message == "Could not process file"
        assert (
            by_id["18932"].error_detail
            == "Thumb_ESPR.png: docling rejected PNG (no OCR)"
        )
        assert by_id["19397"].state == JobFileState.INGESTING.value

        db.refresh(job)
        assert job.progress_current == 2  # INGESTED + FAILED
        assert job.progress_total == 3  # grows to observed row count
        # derived from the most recent file update
        assert "Timeline_ESPR.png" in (job.progress_message or "")

    def test_total_files_respects_declared_total(
        self, db: Session, test_user: User
    ) -> None:
        """Worker-declared total_files isn't overwritten by row count."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        job_repo.update_progress(job.id, total_files=42)
        job_repo.update_progress(
            job.id,
            file={
                "external_file_id": "1",
                "filename": "one.pdf",
                "state": JobFileState.INGESTED.value,
            },
        )

        db.refresh(job)
        assert job.progress_total == 42
        assert job.progress_current == 1

    def test_get_job_files_returns_stable_order(
        self, db: Session, test_user: User
    ) -> None:
        """Rows in creation order so pollers see a stable shape."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        for ext_id, name in [("1", "a.pdf"), ("2", "b.pdf"), ("3", "c.pdf")]:
            job_repo.update_progress(
                job.id,
                file={
                    "external_file_id": ext_id,
                    "filename": name,
                    "state": JobFileState.INGESTING.value,
                },
            )

        # mutate the middle row's state, order must not change
        job_repo.update_progress(
            job.id,
            file={
                "external_file_id": "2",
                "filename": "b.pdf",
                "state": JobFileState.INGESTED.value,
            },
        )

        files = job_repo.get_job_files(job.id)
        assert [f.external_file_id for f in files] == ["1", "2", "3"]
        assert files[1].state == JobFileState.INGESTED.value

    def test_get_job_files_empty_for_jobs_with_no_files(
        self, db: Session, test_user: User
    ) -> None:
        """Returns [] not None when there's no per-file tracking."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.METADATA_SYNC, user_id=test_user.id)
        assert job_repo.get_job_files(job.id) == []

    def test_weighted_progress_advances_on_intermediate_states(
        self, db: Session, test_user: User
    ) -> None:
        """Raw counter reads 0% when no file is terminal; weighted helper
        must give a non-zero value so the UI bar moves."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        job_repo.update_progress(
            job.id,
            file={
                "external_file_id": "a",
                "filename": "a.pdf",
                "state": JobFileState.INGESTING.value,
            },
        )
        job_repo.update_progress(
            job.id,
            file={
                "external_file_id": "b",
                "filename": "b.pdf",
                "state": JobFileState.DOWNLOADING.value,
            },
        )

        # stored counters: 0/2 = 0%, that's the bug
        db.refresh(job)
        assert job.progress_current == 0

        # weighted: (0.5 + 0.05) / 2 * 100 = 27.5
        pct = job_repo.get_weighted_progress_percentage(job.id)
        assert pct == 27.5

    def test_weighted_progress_reaches_100_when_all_terminal(
        self, db: Session, test_user: User
    ) -> None:
        """All terminal files give 100, matching the raw-counter behavior."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        for ext_id, state in [
            ("a", JobFileState.INGESTED),
            ("b", JobFileState.FAILED),
            ("c", JobFileState.SKIPPED),
        ]:
            job_repo.update_progress(
                job.id,
                file={
                    "external_file_id": ext_id,
                    "filename": f"{ext_id}.pdf",
                    "state": state.value,
                },
            )

        assert job_repo.get_weighted_progress_percentage(job.id) == 100.0

    def test_weighted_progress_returns_none_for_jobs_without_files(
        self, db: Session, test_user: User
    ) -> None:
        """No JobFile rows returns None so callers fall back to counters."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.METADATA_SYNC, user_id=test_user.id)
        assert job_repo.get_weighted_progress_percentage(job.id) is None

    def test_explicit_message_wins_over_derived(
        self, db: Session, test_user: User
    ) -> None:
        """Explicit aggregate message wins over derived per-file one."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        job_repo.update_progress(
            job.id,
            message="Batch 3 of 5",
            file={
                "external_file_id": "1",
                "filename": "one.pdf",
                "state": JobFileState.INGESTING.value,
            },
        )

        db.refresh(job)
        assert job.progress_message == "Batch 3 of 5"


class TestJobQueries:
    def test_get_by_user_filters_correctly(self, db: Session, test_user: User) -> None:
        job_repo = JobRepository(db)

        job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.create_job(job_type=JobType.METADATA_SYNC, user_id=test_user.id)

        other_user = User(email="other@example.com", is_active=True)
        db.add(other_user)
        db.commit()
        job_repo.create_job(job_type=JobType.INGESTION, user_id=other_user.id)

        user_jobs = job_repo.get_by_user(test_user.id)

        assert len(user_jobs) == 2
        assert all(j.user_id == test_user.id for j in user_jobs)

    def test_get_by_user_filters_by_status(self, db: Session, test_user: User) -> None:
        job_repo = JobRepository(db)

        job1 = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job2 = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job1.id)

        running_jobs = job_repo.get_by_user(test_user.id, status=JobStatus.RUNNING)
        pending_jobs = job_repo.get_by_user(test_user.id, status=JobStatus.PENDING)

        assert len(running_jobs) == 1
        assert running_jobs[0].id == job1.id
        assert len(pending_jobs) == 1
        assert pending_jobs[0].id == job2.id


class TestJobEvents:
    def test_events_logged_on_state_changes(self, db: Session, test_user: User) -> None:
        """State transitions create event log entries."""
        job_repo = JobRepository(db)

        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)
        job_repo.complete_job(job.id)

        events = job_repo.get_job_events(job.id)

        # created, pending->running, running->completed
        assert len(events) >= 3
        event_types = [e.event_type for e in events]
        assert "created" in event_types


class TestJobCleanup:
    def test_cleanup_old_jobs(self, db: Session, test_user: User) -> None:
        """Old completed jobs are deleted."""
        job_repo = JobRepository(db)

        old_job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(old_job.id)
        job_repo.complete_job(old_job.id)
        old_job.created_at = datetime.now(UTC) - timedelta(days=60)
        db.commit()

        recent_job = job_repo.create_job(
            job_type=JobType.INGESTION, user_id=test_user.id
        )
        job_repo.start_job(recent_job.id)
        job_repo.complete_job(recent_job.id)

        deleted_count = job_repo.cleanup_old_jobs(days=30)

        assert deleted_count == 1
        assert job_repo.get(old_job.id) is None
        assert job_repo.get(recent_job.id) is not None

    def test_cleanup_preserves_running_jobs(self, db: Session, test_user: User) -> None:
        """Running jobs are not deleted even if old."""
        job_repo = JobRepository(db)

        running_job = job_repo.create_job(
            job_type=JobType.INGESTION, user_id=test_user.id
        )
        job_repo.start_job(running_job.id)
        running_job.created_at = datetime.now(UTC) - timedelta(days=60)
        db.commit()

        deleted_count = job_repo.cleanup_old_jobs(days=30)

        assert deleted_count == 0
        assert job_repo.get(running_job.id) is not None
