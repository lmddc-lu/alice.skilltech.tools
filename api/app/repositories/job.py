import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.metrics import (
    JOB_FAILURES,
    JOB_PENDING_SECONDS,
    JOB_TOTAL_DURATION_SECONDS,
    JOBS_COMPLETED,
    JOBS_ENQUEUED,
    classify_error_kind,
)
from app.models.enums import (
    JOB_FILE_DONE_STATES,
    DataSourceSyncStatus,
    JobFileState,
    JobStatus,
    JobType,
    KnowledgeBaseStatus,
)
from app.models.tables import (
    DataSource,
    Job,
    JobEvent,
    JobFile,
    KnowledgeBase,
)
from app.repositories.base import BaseRepository


def _job_age_seconds(job: Job, until: datetime) -> float:
    created = job.created_at
    if created.tzinfo is None:
        # legacy rows may have been written without tz info; assume UTC.
        created = created.replace(tzinfo=UTC)
    return (until - created).total_seconds()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class JobRepository(BaseRepository[Job]):
    def __init__(self, session: Session):
        super().__init__(session, Job)

    def create_job(
        self,
        job_type: JobType,
        user_id: UUID,
        datasource_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
        input_params: dict[str, Any] | None = None,
    ) -> Job:
        job = Job(
            job_type=job_type.value,
            user_id=user_id,
            datasource_id=datasource_id,
            knowledge_base_id=knowledge_base_id,
            input_params=json.dumps(input_params) if input_params else None,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)

        self._log_event(job.id, "created", new_status=JobStatus.PENDING.value)
        JOBS_ENQUEUED.labels(job_type=job.job_type).inc()

        return job

    def start_job(self, job_id: UUID) -> Job | None:
        job = self.get(job_id)
        if not job:
            return None

        old_status = job.status
        now = datetime.now(UTC)
        job.status = JobStatus.RUNNING.value
        job.started_at = now
        # seed so stale detection has a baseline from job start, even if no
        # progress messages have been published yet
        job.progress_updated_at = now
        self.session.commit()

        self._log_event(job_id, "status_change", old_status, JobStatus.RUNNING.value)
        # pending → running is the only transition that observes queue wait;
        # if the worker never reports back (job goes straight from PENDING to
        # STALLED) we don't observe pending_seconds, by design — that case is
        # already counted via jobs_completed_total{status="stalled"}.
        JOB_PENDING_SECONDS.labels(job_type=job.job_type).observe(
            _job_age_seconds(job, now)
        )
        return job

    def complete_job(
        self,
        job_id: UUID,
        result_summary: dict[str, Any] | None = None,
    ) -> Job | None:
        """Mark a job as completed. Skips if already cancelled."""
        job = self.get(job_id)
        if not job:
            return None

        if job.status == JobStatus.CANCELLED.value:
            logger.info(f"Job {job_id} already cancelled, skipping completion")
            return None

        old_status = job.status
        now = datetime.now(UTC)
        job.status = JobStatus.COMPLETED.value
        job.completed_at = now
        job.result_summary = json.dumps(result_summary) if result_summary else None
        self.session.commit()

        self._log_event(job_id, "status_change", old_status, JobStatus.COMPLETED.value)
        JOBS_COMPLETED.labels(
            job_type=job.job_type, status=JobStatus.COMPLETED.value
        ).inc()
        JOB_TOTAL_DURATION_SECONDS.labels(
            job_type=job.job_type, status=JobStatus.COMPLETED.value
        ).observe(_job_age_seconds(job, now))
        return job

    def fail_job(
        self,
        job_id: UUID,
        error_message: str,
        error_details: str | None = None,
    ) -> Job | None:
        """Mark a job as failed. Skips if already cancelled."""
        job = self.get(job_id)
        if not job:
            return None

        if job.status == JobStatus.CANCELLED.value:
            logger.info(f"Job {job_id} already cancelled, skipping failure")
            return None

        old_status = job.status
        now = datetime.now(UTC)
        job.status = JobStatus.FAILED.value
        job.completed_at = now
        job.error_message = error_message
        job.error_details = error_details
        self.session.commit()

        self._log_event(
            job_id, "status_change", old_status, JobStatus.FAILED.value, error_message
        )
        JOBS_COMPLETED.labels(
            job_type=job.job_type, status=JobStatus.FAILED.value
        ).inc()
        JOB_TOTAL_DURATION_SECONDS.labels(
            job_type=job.job_type, status=JobStatus.FAILED.value
        ).observe(_job_age_seconds(job, now))
        JOB_FAILURES.labels(
            job_type=job.job_type, error_kind=classify_error_kind(error_message)
        ).inc()
        return job

    # weights for weighted progress. terminal states are 1.0. INGESTING
    # carries most of the weight because Docling is by far the slowest step.
    _PROGRESS_STATE_WEIGHTS: dict[str, float] = {
        JobFileState.PENDING.value: 0.0,
        JobFileState.DOWNLOADING.value: 0.05,
        JobFileState.DOWNLOADED.value: 0.15,
        JobFileState.INGESTING.value: 0.5,
        JobFileState.INGESTED.value: 1.0,
        JobFileState.SKIPPED.value: 1.0,
        JobFileState.FAILED.value: 1.0,
    }

    # fail loudly if someone adds a JobFileState without a weight, instead
    # of silently defaulting via .get(..., 0.0)
    assert set(_PROGRESS_STATE_WEIGHTS) == {s.value for s in JobFileState}, (
        "JobFileState enum and _PROGRESS_STATE_WEIGHTS out of sync"
    )

    @classmethod
    def _percentage_from_state_counts(
        cls, state_counts: list[tuple[str, int]]
    ) -> float:
        total = sum(count for _, count in state_counts)
        if total == 0:
            return 0.0
        weighted = 0.0
        for state, count in state_counts:
            weight = cls._PROGRESS_STATE_WEIGHTS.get(state)
            if weight is None:
                logger.warning(
                    f"Unknown JobFile state {state!r} in progress computation; "
                    f"treating as 0 weight"
                )
                weight = 0.0
            weighted += weight * count
        return round(weighted / total * 100, 1)

    def get_weighted_progress_percentage(self, job_id: UUID) -> float | None:
        """Smooth 0..100 progress for a single job.

        Unlike progress_current/progress_total (only advances on terminal
        states), this weights each file by pipeline position so the bar
        ticks forward while long files are mid-flight in Docling.

        Returns None when the job has no JobFile rows, callers fall back
        to the stored counters.
        """
        return self.get_weighted_progress_percentages_bulk([job_id]).get(job_id)

    def get_weighted_progress_percentages_bulk(
        self, job_ids: list[UUID]
    ) -> dict[UUID, float]:
        """{job_id: percentage} for jobs that have JobFile rows.

        Single grouped query regardless of input size. List endpoints call
        this once instead of N per-job lookups. Jobs missing from the
        result have no per-file tracking, callers fall back to stored
        counters.
        """
        if not job_ids:
            return {}
        rows = self.session.exec(
            select(JobFile.job_id, JobFile.state, func.count())
            .where(col(JobFile.job_id).in_(job_ids))
            .group_by(col(JobFile.job_id), col(JobFile.state))
        ).all()

        per_job: dict[UUID, list[tuple[str, int]]] = {}
        for job_id, state, count in rows:
            per_job.setdefault(job_id, []).append((state, count))

        return {
            job_id: self._percentage_from_state_counts(state_counts)
            for job_id, state_counts in per_job.items()
        }

    @staticmethod
    def _fallback_percentage(job: Job) -> float:
        if job.progress_total and job.progress_total > 0:
            return round(job.progress_current / job.progress_total * 100, 1)
        return 0.0

    def get_progress_percentage(self, job: Job) -> float:
        """Prefers weighted per-file, falls back to stored counters."""
        weighted = self.get_weighted_progress_percentage(job.id)
        return weighted if weighted is not None else self._fallback_percentage(job)

    def get_progress_percentages_bulk(self, jobs: list[Job]) -> dict[UUID, float]:
        """Batched get_progress_percentage. Avoids N+1 in list endpoints."""
        weighted_map = self.get_weighted_progress_percentages_bulk([j.id for j in jobs])
        return {
            j.id: (
                weighted_map[j.id]
                if j.id in weighted_map
                else self._fallback_percentage(j)
            )
            for j in jobs
        }

    @staticmethod
    def get_deferred_state(job: Job) -> dict[str, Any] | None:
        """Deferred-ingestion details if the job is parked, else None.

        An ingestion is deferred while a Moodle metadata sync runs for
        its datasources. The payload + waiting list live in
        ``input_params.deferred_ingestion`` ; see IndexingService for
        where it's set. Used by serializers to distinguish "waiting on
        metadata refresh" from "stalled at 0%".
        """
        if not job.input_params:
            return None
        try:
            params = json.loads(job.input_params)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(params, dict):
            return None
        deferred = params.get("deferred_ingestion")
        if not isinstance(deferred, dict):
            return None
        waiting = deferred.get("waiting_for_datasources") or []
        if not waiting:
            return None
        return {"waiting_for_datasources": list(waiting)}

    def get_job_files(self, job_id: UUID) -> list[JobFile]:
        """JobFile rows for a job, ordered created_at asc.

        Stable ordering so pollers see the same shape across calls, new
        files appear at the tail.
        """
        statement = (
            select(JobFile)
            .where(JobFile.job_id == job_id)
            .order_by(col(JobFile.created_at).asc())
        )
        return list(self.session.exec(statement))

    def update_progress(
        self,
        job_id: UUID,
        *,
        message: str | None = None,
        total_files: int | None = None,
        file: dict[str, Any] | None = None,
    ) -> Job | None:
        """Apply a progress update.

        Every call bumps progress_updated_at so stale detection sees the
        job as alive. ``file`` upserts a per-file row in jobfile and
        recomputes progress_current from terminal states.

        Args:
            job_id: Job to update.
            message: Optional aggregate progress message.
            total_files: Sets progress_total directly. Worker publishes
                this once at the start of a run.
            file: Optional per-file transition with keys external_file_id,
                filename, state, error_message, error_detail, error_code.
        """
        job = self.get(job_id)
        if not job:
            return None

        now = datetime.now(UTC)
        job.progress_updated_at = now

        if total_files is not None:
            job.progress_total = total_files

        if file is not None:
            self._upsert_job_file(job, file, now)

        # explicit message wins over derived per-file message
        if message is not None:
            job.progress_message = message

        self.session.commit()
        return job

    def _upsert_job_file(self, job: Job, file: dict[str, Any], now: datetime) -> None:
        """Upsert a JobFile row and refresh denormalized Job counters.

        Does not commit, caller owns the transaction.
        """
        external_id = file.get("external_file_id")
        if not external_id:
            logger.warning(
                f"Progress update for job {job.id} has file without external_file_id; skipping"
            )
            return

        state = file.get("state") or JobFileState.PENDING.value
        filename = file.get("filename") or external_id
        error_message = file.get("error_message")
        error_detail = file.get("error_detail")
        error_code = file.get("error_code")

        existing = self.session.exec(
            select(JobFile).where(
                JobFile.job_id == job.id,
                JobFile.external_file_id == external_id,
            )
        ).first()

        if existing is None:
            self.session.add(
                JobFile(
                    job_id=job.id,
                    external_file_id=external_id,
                    filename=filename,
                    state=state,
                    error_message=error_message,
                    error_detail=error_detail,
                    error_code=error_code,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            existing.state = state
            existing.filename = filename
            existing.error_message = error_message
            existing.error_detail = error_detail
            existing.error_code = error_code
            existing.updated_at = now

        # flush so the recount below sees the row we just upserted
        self.session.flush()

        # single grouped query (previously two separate COUNTs per message)
        rows = self.session.exec(
            select(JobFile.state, func.count())
            .where(JobFile.job_id == job.id)
            .group_by(JobFile.state)
        ).all()
        total_count = sum(count for _, count in rows)
        done_count = sum(
            count for row_state, count in rows if row_state in JOB_FILE_DONE_STATES
        )

        job.progress_current = int(done_count)
        # max(declared, observed) so explicit totals are respected and lazy
        # upserts still grow the counter when no total was declared
        job.progress_total = max(job.progress_total, int(total_count))
        # derived, callers can override via ``message``
        job.progress_message = f"{filename} ({state})"

    def get_by_user(
        self,
        user_id: UUID,
        job_type: JobType | None = None,
        status: JobStatus | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Job]:
        statement = select(Job).where(Job.user_id == user_id)

        if job_type:
            statement = statement.where(Job.job_type == job_type.value)
        if status:
            statement = statement.where(Job.status == status.value)

        statement = (
            statement.order_by(col(Job.created_at).desc()).offset(skip).limit(limit)
        )
        return list(self.session.exec(statement))

    def get_active_jobs(self, user_id: UUID | None = None) -> list[Job]:
        statement = select(Job).where(
            col(Job.status).in_([JobStatus.PENDING.value, JobStatus.RUNNING.value])
        )
        if user_id:
            statement = statement.where(Job.user_id == user_id)

        return list(self.session.exec(statement))

    def get_active_for_knowledge_base(self, kb_id: UUID) -> Job | None:
        statement = select(Job).where(
            Job.knowledge_base_id == kb_id,
            col(Job.status).in_(["pending", "running"]),
        )
        return self.session.exec(statement).first()

    def get_latest_for_knowledge_base(self, kb_id: UUID) -> Job | None:
        """Latest job for a knowledge base.

        Active (pending/running) jobs take precedence so the live progress
        UI reflects the current sync. Otherwise returns the most recent
        job regardless of age (the previous 5-minute cutoff hid past
        failures after API restarts). Callers that only want live jobs
        should use ``get_active_for_knowledge_base``.
        """
        active = self.get_active_for_knowledge_base(kb_id)
        if active:
            return active

        statement = (
            select(Job)
            .where(Job.knowledge_base_id == kb_id)
            .order_by(col(Job.created_at).desc())
            .limit(1)
        )
        return self.session.exec(statement).first()

    def get_recent_jobs(
        self,
        hours: int = 24,
        job_type: JobType | None = None,
    ) -> list[Job]:
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        statement = select(Job).where(Job.created_at >= cutoff)

        if job_type:
            statement = statement.where(Job.job_type == job_type.value)

        statement = statement.order_by(col(Job.created_at).desc())
        return list(self.session.exec(statement))

    def get_job_stats(
        self,
        hours: int = 24,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        cutoff = datetime.now(UTC) - timedelta(hours=hours)

        base_query = select(Job).where(Job.created_at >= cutoff)
        if user_id:
            base_query = base_query.where(Job.user_id == user_id)

        jobs = list(self.session.exec(base_query))

        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        stats: dict[str, Any] = {
            "total": len(jobs),
            "by_status": by_status,
            "by_type": by_type,
            "avg_duration_seconds": None,
            "success_rate": None,
        }

        completed_durations = []
        completed_count = 0
        failed_count = 0

        for job in jobs:
            by_status[job.status] = by_status.get(job.status, 0) + 1
            by_type[job.job_type] = by_type.get(job.job_type, 0) + 1

            if job.status == JobStatus.COMPLETED.value:
                completed_count += 1
                if job.started_at and job.completed_at:
                    duration = (job.completed_at - job.started_at).total_seconds()
                    completed_durations.append(duration)
            elif job.status == JobStatus.FAILED.value:
                failed_count += 1

        if completed_durations:
            stats["avg_duration_seconds"] = sum(completed_durations) / len(
                completed_durations
            )

        total_finished = completed_count + failed_count
        if total_finished > 0:
            stats["success_rate"] = completed_count / total_finished

        return stats

    def get_job_events(self, job_id: UUID) -> list[JobEvent]:
        statement = (
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(col(JobEvent.created_at).asc())
        )
        return list(self.session.exec(statement))

    def find_by_entity(
        self,
        datasource_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
        status: JobStatus | None = None,
    ) -> list[Job]:
        statement = select(Job)

        if datasource_id:
            statement = statement.where(Job.datasource_id == datasource_id)
        if knowledge_base_id:
            statement = statement.where(Job.knowledge_base_id == knowledge_base_id)
        if status:
            statement = statement.where(Job.status == status.value)

        statement = statement.order_by(col(Job.created_at).desc())
        return list(self.session.exec(statement))

    def cleanup_old_jobs(self, days: int = 30) -> int:
        """Delete completed/failed jobs older than N days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)

        statement = select(Job).where(
            Job.created_at < cutoff,
            col(Job.status).in_([JobStatus.COMPLETED.value, JobStatus.FAILED.value]),
        )
        old_jobs = list(self.session.exec(statement))

        for job in old_jobs:
            # events cascade
            self.session.delete(job)

        self.session.commit()
        return len(old_jobs)

    def _log_event(
        self,
        job_id: UUID,
        event_type: str,
        old_status: str | None = None,
        new_status: str | None = None,
        message: str | None = None,
    ) -> None:
        event = JobEvent(
            job_id=job_id,
            event_type=event_type,
            old_status=old_status,
            new_status=new_status,
            message=message,
        )
        self.session.add(event)
        self.session.commit()

    def get_all_jobs(
        self,
        job_type: JobType | None = None,
        status: JobStatus | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Job]:
        """All jobs with optional filters (admin)."""
        statement = select(Job)

        if job_type:
            statement = statement.where(Job.job_type == job_type.value)
        if status:
            statement = statement.where(Job.status == status.value)

        statement = (
            statement.order_by(col(Job.created_at).desc()).offset(skip).limit(limit)
        )
        return list(self.session.exec(statement))

    def mark_stalled_jobs(
        self,
        running_stale_minutes: int = 30,
        running_absolute_minutes: int = 360,
        pending_timeout_minutes: int = 120,
    ) -> list[Job]:
        """Find and mark stuck jobs.

        A RUNNING job is stalled when either:
        - no progress update for ``running_stale_minutes`` (silent job,
          Docling wedged, worker crashed), or
        - ``running_absolute_minutes`` elapsed since ``started_at`` (hard
          ceiling, even progressing jobs get reaped eventually).

        A PENDING job is stalled after ``pending_timeout_minutes`` without
        being picked up.

        Callers should broadcast cancellation for the returned jobs (via
        broadcast_job_cancellations) so workers stop processing them.
        """

        now = datetime.now(UTC)
        stalled_jobs: list[Job] = []

        stale_cutoff = now - timedelta(minutes=running_stale_minutes)
        absolute_cutoff = now - timedelta(minutes=running_absolute_minutes)
        pending_cutoff = now - timedelta(minutes=pending_timeout_minutes)

        # absolute runtime takes priority over stale: the job is over no
        # matter how it's progressing, so tag with that reason first and
        # skip it in the stale sweep
        absolute_statement = select(Job).where(
            Job.status == JobStatus.RUNNING.value,
            col(Job.started_at) < absolute_cutoff,
        )
        stuck_absolute = list(self.session.exec(absolute_statement))

        # coalesce progress_updated_at with started_at so jobs that never
        # published progress still get a baseline from their start
        stale_statement = select(Job).where(
            Job.status == JobStatus.RUNNING.value,
            func.coalesce(Job.progress_updated_at, Job.started_at) < stale_cutoff,
        )
        stuck_stale = list(self.session.exec(stale_statement))

        pending_statement = select(Job).where(
            Job.status == JobStatus.PENDING.value,
            Job.created_at < pending_cutoff,
        )
        stuck_pending = list(self.session.exec(pending_statement))

        seen: set[UUID] = set()

        for job in stuck_absolute:
            if job.id in seen:
                continue
            seen.add(job.id)
            self._mark_stalled(
                job,
                f"Job exceeded absolute runtime of {running_absolute_minutes}min",
            )
            stalled_jobs.append(job)

        for job in stuck_stale:
            if job.id in seen:
                continue
            seen.add(job.id)
            last_progress = job.progress_updated_at or job.started_at
            self._mark_stalled(
                job,
                f"Job stalled: no progress since {last_progress} "
                f"(stale window {running_stale_minutes}min)",
            )
            stalled_jobs.append(job)

        for job in stuck_pending:
            if job.id in seen:
                continue
            seen.add(job.id)
            self._mark_stalled(
                job,
                f"Pending job stalled: not picked up within "
                f"{pending_timeout_minutes}min",
            )
            stalled_jobs.append(job)

        if stalled_jobs:
            self.session.commit()
            logger.info(f"Marked {len(stalled_jobs)} jobs as stalled")

        return stalled_jobs

    def mark_all_running_as_stalled(self) -> list[Job]:
        """Mark every RUNNING and PENDING job as stalled, unconditionally.

        Called by the API startup hook to reap jobs that were in-flight at
        last shutdown. We can't distinguish a crashed worker from a
        graceful restart, so we conservatively assume orphaned and let the
        user retry.
        """
        running_statement = select(Job).where(
            col(Job.status).in_([JobStatus.RUNNING.value, JobStatus.PENDING.value])
        )
        stuck = list(self.session.exec(running_statement))

        for job in stuck:
            self._mark_stalled(job, "Job orphaned by API restart: retry to re-run.")

        if stuck:
            self.session.commit()
            logger.info(f"Startup: marked {len(stuck)} orphaned jobs as stalled")

        return stuck

    def _mark_stalled(self, job: Job, reason: str) -> None:
        """Transition a job to STALLED and reset linked KB/datasource.

        Does not commit, caller batches the commit for the full sweep.
        """
        old_status = job.status
        now = datetime.now(UTC)
        job.status = JobStatus.STALLED.value
        job.error_message = reason
        JOBS_COMPLETED.labels(
            job_type=job.job_type, status=JobStatus.STALLED.value
        ).inc()
        JOB_TOTAL_DURATION_SECONDS.labels(
            job_type=job.job_type, status=JobStatus.STALLED.value
        ).observe(_job_age_seconds(job, now))

        if job.knowledge_base_id:
            kb = self.session.get(KnowledgeBase, job.knowledge_base_id)
            if kb and kb.status == KnowledgeBaseStatus.PROCESSING:
                kb.status = KnowledgeBaseStatus.ERROR
                kb.last_sync_error = (
                    f"Indexing job {job.id} stalled - you can retry reindexing"
                )
                logger.info(f"Reset knowledge base {kb.id} status to 'error'")

        if job.datasource_id:
            ds = self.session.get(DataSource, job.datasource_id)
            if ds and ds.sync_status == DataSourceSyncStatus.PROCESSING:
                ds.sync_status = DataSourceSyncStatus.ERROR
                ds.last_sync_error = (
                    f"Sync job {job.id} stalled - you can retry syncing"
                )
                logger.info(f"Reset datasource {ds.id} status to 'error'")

        self._log_event(
            job.id,
            "stalled",
            old_status=old_status,
            new_status=JobStatus.STALLED.value,
            message=reason,
        )
