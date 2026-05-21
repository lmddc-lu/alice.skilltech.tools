import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import settings
from app.core.metrics import JOBS_IN_STATE, MONITORING_RABBITMQ_POLL
from app.models.enums import JobStatus
from app.models.tables import Job
from app.repositories.job import JobRepository

logger = logging.getLogger(__name__)

# limit gauge cardinality to lifecycle states that actually appear in the DB
_TRACKED_JOB_STATES: tuple[str, ...] = tuple(s.value for s in JobStatus)


@dataclass
class QueueHealth:
    name: str
    messages_ready: int
    messages_unacked: int
    consumers: int
    is_healthy: bool
    warning: str | None = None


@dataclass
class SystemHealth:
    rabbitmq_connected: bool
    database_connected: bool
    queues: list[QueueHealth]
    active_jobs: int
    failed_jobs_24h: int
    avg_job_duration: float | None
    overall_status: str  # healthy, degraded, unhealthy


class MonitoringService:
    QUEUE_NAMES = [
        "metadata_sync_jobs",
        "metadata_sync_jobs_completed",
        "metadata_sync_jobs_failed",
        "content_sync_jobs",
        "content_sync_jobs_completed",
        "content_sync_jobs_failed",
        "ingestion_jobs",
        "ingestion_jobs_completed",
        "ingestion_jobs_failed",
    ]

    def __init__(self, session: Session):
        self.session = session
        self.job_repo = JobRepository(session)

    async def get_system_health(self) -> SystemHealth:
        rabbitmq_connected = await self._check_rabbitmq_connection()
        queues = await self._get_queue_health() if rabbitmq_connected else []

        try:
            stats = self.job_repo.get_job_stats(hours=24)
            database_connected = True
            active_jobs = stats["by_status"].get(JobStatus.RUNNING.value, 0)
            active_jobs += stats["by_status"].get(JobStatus.PENDING.value, 0)
            failed_jobs = stats["by_status"].get(JobStatus.FAILED.value, 0)
            avg_duration = stats["avg_duration_seconds"]
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            database_connected = False
            active_jobs = 0
            failed_jobs = 0
            avg_duration = None

        if not rabbitmq_connected or not database_connected:
            overall_status = "unhealthy"
        elif any(not q.is_healthy for q in queues):
            overall_status = "degraded"
        elif failed_jobs > 10:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        return SystemHealth(
            rabbitmq_connected=rabbitmq_connected,
            database_connected=database_connected,
            queues=queues,
            active_jobs=active_jobs,
            failed_jobs_24h=failed_jobs,
            avg_job_duration=avg_duration,
            overall_status=overall_status,
        )

    async def _check_rabbitmq_connection(self) -> bool:
        outcome = "error"
        try:
            # assumes management plugin on default port 15672
            rabbitmq_url = settings.RABBITMQ_URL
            if "@" in rabbitmq_url:
                host_part = rabbitmq_url.split("@")[1]
                host = host_part.split(":")[0]
                credentials_part = rabbitmq_url.split("@")[0].split("://")[1]
                user = credentials_part.split(":")[0]
                password = credentials_part.split(":")[1]
            else:
                host = "localhost"

            management_url = f"http://{host}:15672/api/overview"
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    management_url,
                    auth=(user, password),
                    timeout=5.0,
                )
                if response.status_code == 200:
                    outcome = "ok"
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"RabbitMQ health check failed: {e}")
            return False
        finally:
            MONITORING_RABBITMQ_POLL.labels(endpoint="overview", outcome=outcome).inc()

    async def _get_queue_health(self) -> list[QueueHealth]:
        queues = []

        try:
            rabbitmq_url = settings.RABBITMQ_URL
            if "@" in rabbitmq_url:
                host_part = rabbitmq_url.split("@")[1]
                host = host_part.split(":")[0]
                credentials_part = rabbitmq_url.split("@")[0].split("://")[1]
                user = credentials_part.split(":")[0]
                password = credentials_part.split(":")[1]
            else:
                host = "localhost"

            async with httpx.AsyncClient() as client:
                for queue_name in self.QUEUE_NAMES:
                    poll_outcome = "error"
                    try:
                        response = await client.get(
                            f"http://{host}:15672/api/queues/%2F/{queue_name}",
                            auth=(user, password),
                            timeout=5.0,
                        )

                        if response.status_code == 200:
                            poll_outcome = "ok"
                            data = response.json()
                            messages_ready = data.get("messages_ready", 0)
                            messages_unacked = data.get("messages_unacknowledged", 0)
                            consumers = data.get("consumers", 0)

                            warning = None
                            is_healthy = True

                            if (
                                consumers == 0
                                and "completed" not in queue_name
                                and "failed" not in queue_name
                            ):
                                warning = "No consumers attached"
                                is_healthy = False
                            elif messages_ready > 1000:
                                warning = f"High message backlog: {messages_ready}"
                                is_healthy = False
                            elif messages_unacked > 100:
                                warning = (
                                    f"Many unacknowledged messages: {messages_unacked}"
                                )

                            queues.append(
                                QueueHealth(
                                    name=queue_name,
                                    messages_ready=messages_ready,
                                    messages_unacked=messages_unacked,
                                    consumers=consumers,
                                    is_healthy=is_healthy,
                                    warning=warning,
                                )
                            )
                        else:
                            queues.append(
                                QueueHealth(
                                    name=queue_name,
                                    messages_ready=0,
                                    messages_unacked=0,
                                    consumers=0,
                                    is_healthy=False,
                                    warning="Queue not found",
                                )
                            )
                    except Exception as e:
                        logger.warning(f"Failed to check queue {queue_name}: {e}")
                        queues.append(
                            QueueHealth(
                                name=queue_name,
                                messages_ready=0,
                                messages_unacked=0,
                                consumers=0,
                                is_healthy=False,
                                warning=str(e),
                            )
                        )
                    finally:
                        MONITORING_RABBITMQ_POLL.labels(
                            endpoint="queue", outcome=poll_outcome
                        ).inc()
        except Exception as e:
            logger.error(f"Failed to get queue health: {e}")

        return queues

    def refresh_jobs_in_state_gauge(self) -> None:
        """Re-set the JOBS_IN_STATE gauge to the current DB counts.

        Cheap single query: GROUP BY status. Called from the scheduler so
        the gauge tracks lifecycle inventory without depending on someone
        hitting the monitoring HTTP endpoint.
        """
        try:
            rows = self.session.exec(
                select(Job.status, func.count(Job.id)).group_by(Job.status)
            ).all()
        except Exception as e:
            logger.warning(f"Failed to refresh jobs_in_state gauge: {e}")
            return

        counts: dict[str, int] = {state: int(n) for state, n in rows}
        # write every tracked state (even zero) so the gauge has stable
        # label cardinality and decays to 0 when a state empties out
        for state in _TRACKED_JOB_STATES:
            JOBS_IN_STATE.labels(state=state).set(counts.get(state, 0))

    def get_job_dashboard_data(
        self,
        user_id: UUID | None = None,
        hours: int = 24,
    ) -> dict[str, Any]:
        stats = self.job_repo.get_job_stats(hours=hours, user_id=user_id)
        active_jobs = self.job_repo.get_active_jobs(user_id=user_id)
        recent_failed = [
            j
            for j in self.job_repo.get_recent_jobs(hours=hours)
            if j.status == JobStatus.FAILED.value
        ][:10]

        return {
            "stats": stats,
            "active_jobs": self.jobs_to_dicts(active_jobs),
            "recent_failures": self.jobs_to_dicts(recent_failed),
            "time_range_hours": hours,
        }

    def jobs_to_dicts(self, jobs: list[Job]) -> list[dict[str, Any]]:
        """Batched _job_to_dict for list endpoints; one grouped query instead of N."""
        if not jobs:
            return []
        pct_map = self.job_repo.get_progress_percentages_bulk(jobs)
        return [self._job_to_dict(j, percentage=pct_map[j.id]) for j in jobs]

    def _job_to_dict(self, job: Job, percentage: float | None = None) -> dict[str, Any]:
        # list callers pass precomputed percentage to avoid the per-job query
        if percentage is None:
            percentage = self.job_repo.get_progress_percentage(job)
        deferred = self.job_repo.get_deferred_state(job)
        phase = "waiting_metadata" if deferred else None
        progress_message = job.progress_message
        if deferred and not progress_message:
            n = len(deferred["waiting_for_datasources"])
            progress_message = (
                f"Waiting on Moodle metadata refresh ({n} datasource"
                f"{'s' if n != 1 else ''})"
            )
        return {
            "id": str(job.id),
            "job_type": job.job_type,
            "status": job.status,
            "phase": phase,
            "user_id": str(job.user_id),
            "datasource_id": str(job.datasource_id) if job.datasource_id else None,
            "knowledge_base_id": str(job.knowledge_base_id)
            if job.knowledge_base_id
            else None,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "progress": {
                "current": job.progress_current,
                "total": job.progress_total,
                "message": progress_message,
                "percentage": percentage,
            },
            "error_message": job.error_message,
            "duration_seconds": (
                (job.completed_at - job.started_at).total_seconds()
                if job.started_at and job.completed_at
                else None
            ),
        }
