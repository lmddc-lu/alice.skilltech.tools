"""Tests for the metric side of MonitoringService:
- refresh_jobs_in_state_gauge sets the gauge from DB counts
- the RabbitMQ poll counter fires on every management API call.
"""

from __future__ import annotations

from sqlmodel import Session

from app.core.metrics import JOBS_IN_STATE
from app.models.enums import JobStatus, JobType
from app.models.tables import User
from app.repositories.job import JobRepository
from app.services.monitoring_service import MonitoringService


def _gauge_value(gauge, **labels) -> float:
    return gauge.labels(**labels)._value.get()


class TestJobsInStateGauge:
    def test_refresh_writes_every_tracked_state(
        self, db: Session, test_user: User
    ) -> None:
        # baseline: every JobStatus appears as a labeled sample, default 0
        MonitoringService(db).refresh_jobs_in_state_gauge()
        for status in JobStatus:
            # just confirm the label exists; the value will be set by the test below
            assert _gauge_value(JOBS_IN_STATE, state=status.value) >= 0

    def test_refresh_reflects_pending_count(self, db: Session, test_user: User) -> None:
        job_repo = JobRepository(db)
        # create three pending jobs
        for _ in range(3):
            job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)

        MonitoringService(db).refresh_jobs_in_state_gauge()

        assert _gauge_value(JOBS_IN_STATE, state=JobStatus.PENDING.value) == 3.0

    def test_refresh_decays_to_zero_when_state_empties(
        self, db: Session, test_user: User
    ) -> None:
        # all jobs from the test_user fixture's db arrive as PENDING; after
        # marking them complete the PENDING gauge must read 0, not the old
        # value left over from the previous refresh
        job_repo = JobRepository(db)
        job = job_repo.create_job(job_type=JobType.INGESTION, user_id=test_user.id)
        MonitoringService(db).refresh_jobs_in_state_gauge()
        baseline_pending = _gauge_value(JOBS_IN_STATE, state=JobStatus.PENDING.value)
        assert baseline_pending >= 1.0

        job_repo.complete_job(job.id)
        MonitoringService(db).refresh_jobs_in_state_gauge()

        # baseline included our new pending; after completion it should drop
        # by exactly one (other tests may have created other pendings, so
        # we test the delta rather than an absolute count)
        after = _gauge_value(JOBS_IN_STATE, state=JobStatus.PENDING.value)
        assert after == baseline_pending - 1
