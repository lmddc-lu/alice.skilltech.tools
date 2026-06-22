"""Tests that JobRepository lifecycle methods bump the right Prometheus
metrics. These guard the dashboard story: each terminal state must emit
exactly one jobs_completed_total event, and failures must classify into a
stable error_kind label.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.core.metrics import (
    ERROR_KIND_AUTH,
    ERROR_KIND_CONNECTION,
    ERROR_KIND_EMPTY_CONTENT,
    ERROR_KIND_OTHER,
    ERROR_KIND_TIMEOUT,
    JOB_FAILURES,
    JOB_PENDING_SECONDS,
    JOB_TOTAL_DURATION_SECONDS,
    JOBS_COMPLETED,
    JOBS_ENQUEUED,
    classify_error_kind,
)
from app.models.enums import JobStatus, JobType
from app.models.tables import User
from app.repositories.job import JobRepository


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def _histogram_count(histogram, **labels) -> float:
    suffix = f"{histogram._name}_count"
    for metric in histogram.collect():
        for sample in metric.samples:
            if sample.name == suffix and sample.labels == labels:
                return sample.value
    return 0.0


class TestEnqueueAndComplete:
    def test_create_job_increments_enqueued(self, db: Session, test_user: User) -> None:
        before = _counter_value(JOBS_ENQUEUED, job_type=JobType.INGESTION.value)

        JobRepository(db).create_job(job_type=JobType.INGESTION, user_id=test_user.id)

        assert (
            _counter_value(JOBS_ENQUEUED, job_type=JobType.INGESTION.value)
            == before + 1
        )

    def test_start_job_observes_pending_seconds(
        self, db: Session, test_user: User
    ) -> None:
        before = _histogram_count(JOB_PENDING_SECONDS, job_type=JobType.INGESTION.value)
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)

        job_repo.start_job(job.id)

        assert (
            _histogram_count(JOB_PENDING_SECONDS, job_type=JobType.INGESTION.value)
            == before + 1
        )

    def test_complete_job_counts_completed_and_duration(
        self, db: Session, test_user: User
    ) -> None:
        before_counter = _counter_value(
            JOBS_COMPLETED,
            job_type=JobType.INGESTION.value,
            status=JobStatus.COMPLETED.value,
        )
        before_hist = _histogram_count(
            JOB_TOTAL_DURATION_SECONDS,
            job_type=JobType.INGESTION.value,
            status=JobStatus.COMPLETED.value,
        )
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        job_repo.complete_job(job.id)

        assert (
            _counter_value(
                JOBS_COMPLETED,
                job_type=JobType.INGESTION.value,
                status=JobStatus.COMPLETED.value,
            )
            == before_counter + 1
        )
        assert (
            _histogram_count(
                JOB_TOTAL_DURATION_SECONDS,
                job_type=JobType.INGESTION.value,
                status=JobStatus.COMPLETED.value,
            )
            == before_hist + 1
        )

    def test_complete_after_cancel_does_not_double_count(
        self, db: Session, test_user: User
    ) -> None:
        """complete_job short-circuits when status is already CANCELLED; the
        metric must not fire otherwise the cancel→complete race would
        produce two terminal events for one job."""
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job.status = JobStatus.CANCELLED.value
        db.commit()

        before = _counter_value(
            JOBS_COMPLETED,
            job_type=JobType.INGESTION.value,
            status=JobStatus.COMPLETED.value,
        )
        result = job_repo.complete_job(job.id)

        assert result is None
        assert (
            _counter_value(
                JOBS_COMPLETED,
                job_type=JobType.INGESTION.value,
                status=JobStatus.COMPLETED.value,
            )
            == before
        )


class TestFailure:
    def test_fail_job_counts_failed_status_and_classifies_error(
        self, db: Session, test_user: User
    ) -> None:
        before_completed = _counter_value(
            JOBS_COMPLETED,
            job_type=JobType.METADATA_SYNC.value,
            status=JobStatus.FAILED.value,
        )
        before_failure = _counter_value(
            JOB_FAILURES,
            job_type=JobType.METADATA_SYNC.value,
            error_kind=ERROR_KIND_AUTH,
        )
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.METADATA_SYNC, user_id=test_user.id)

        job_repo.fail_job(job.id, error_message="Moodle authentication rejected")

        assert (
            _counter_value(
                JOBS_COMPLETED,
                job_type=JobType.METADATA_SYNC.value,
                status=JobStatus.FAILED.value,
            )
            == before_completed + 1
        )
        assert (
            _counter_value(
                JOB_FAILURES,
                job_type=JobType.METADATA_SYNC.value,
                error_kind=ERROR_KIND_AUTH,
            )
            == before_failure + 1
        )

    def test_fail_job_prefers_worker_declared_error_kind(
        self, db: Session, test_user: User
    ) -> None:
        """A worker-declared error_kind wins over message classification:
        the message says "authentication" but the worker knows it was a
        connection failure."""
        before = _counter_value(
            JOB_FAILURES,
            job_type=JobType.METADATA_SYNC.value,
            error_kind=ERROR_KIND_CONNECTION,
        )
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.METADATA_SYNC, user_id=test_user.id)

        job_repo.fail_job(
            job.id,
            error_message="Moodle authentication endpoint unreachable",
            error_kind=ERROR_KIND_CONNECTION,
        )

        assert (
            _counter_value(
                JOB_FAILURES,
                job_type=JobType.METADATA_SYNC.value,
                error_kind=ERROR_KIND_CONNECTION,
            )
            == before + 1
        )

    def test_fail_job_unknown_error_kind_falls_back_to_classification(
        self, db: Session, test_user: User
    ) -> None:
        """An unrecognized error_kind must not become a metric label
        (cardinality guard); fall back to classifying the message."""
        before = _counter_value(
            JOB_FAILURES,
            job_type=JobType.METADATA_SYNC.value,
            error_kind=ERROR_KIND_TIMEOUT,
        )
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.METADATA_SYNC, user_id=test_user.id)

        job_repo.fail_job(
            job.id,
            error_message="Request timed out",
            error_kind="surprise-bucket",
        )

        assert (
            _counter_value(
                JOB_FAILURES,
                job_type=JobType.METADATA_SYNC.value,
                error_kind=ERROR_KIND_TIMEOUT,
            )
            == before + 1
        )


class TestStalledMetrics:
    def test_mark_stalled_records_stalled_status(
        self, db: Session, test_user: User
    ) -> None:
        before = _counter_value(
            JOBS_COMPLETED,
            job_type=JobType.INGESTION.value,
            status=JobStatus.STALLED.value,
        )
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        job_repo.start_job(job.id)

        # push it past the absolute deadline so the sweep grabs it
        job.started_at = datetime.now(UTC) - timedelta(hours=10)
        db.commit()
        stalled = job_repo.mark_stalled_jobs(
            running_stale_minutes=30, running_absolute_minutes=360
        )

        assert len(stalled) == 1
        assert (
            _counter_value(
                JOBS_COMPLETED,
                job_type=JobType.INGESTION.value,
                status=JobStatus.STALLED.value,
            )
            == before + 1
        )


class TestClassifyErrorKind:
    def test_empty_message_is_other(self) -> None:
        assert classify_error_kind(None) == ERROR_KIND_OTHER
        assert classify_error_kind("") == ERROR_KIND_OTHER

    def test_auth_keyword_classifies_auth(self) -> None:
        assert classify_error_kind("Moodle authentication failed") == ERROR_KIND_AUTH

    def test_timeout_classifies_timeout(self) -> None:
        # auth is checked before connection, but timeout must beat connection
        # so a "connection timed out" maps to timeout not connection
        assert classify_error_kind("Connection timed out") == ERROR_KIND_TIMEOUT

    def test_connection_classifies_connection(self) -> None:
        assert (
            classify_error_kind("Connection refused by host") == ERROR_KIND_CONNECTION
        )

    def test_empty_content_classifies(self) -> None:
        assert (
            classify_error_kind("File parsed but no text content extracted")
            == ERROR_KIND_EMPTY_CONTENT
        )

    def test_unknown_falls_back_to_other(self) -> None:
        assert classify_error_kind("KeyError: 'foo'") == ERROR_KIND_OTHER
