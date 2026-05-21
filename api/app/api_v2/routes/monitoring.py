import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api_v2.deps import AdminUser, SessionDep
from app.models.enums import JobStatus, JobType
from app.models.tables import JobFile
from app.repositories.job import JobRepository
from app.services.monitoring_service import MonitoringService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/monitoring", tags=["admin-monitoring"])


# ==================== RESPONSE MODELS ====================


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    user_id: str
    datasource_id: str | None = None
    knowledge_base_id: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    progress: dict[str, Any]
    error_message: str | None = None
    duration_seconds: float | None = None


class JobFileResponse(BaseModel):
    id: str
    external_file_id: str
    filename: str
    state: str
    error_message: str | None = None
    # verbose converter-level detail (e.g. full Docling error), admin only
    error_detail: str | None = None
    # stable JobFileErrorCode value the UI translates against
    error_code: str | None = None
    created_at: str
    updated_at: str


class JobStatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    avg_duration_seconds: float | None = None
    success_rate: float | None = None


class QueueHealthResponse(BaseModel):
    name: str
    messages_ready: int
    messages_unacked: int
    consumers: int
    is_healthy: bool
    warning: str | None = None


class SystemHealthResponse(BaseModel):
    rabbitmq_connected: bool
    database_connected: bool
    queues: list[QueueHealthResponse]
    active_jobs: int
    failed_jobs_24h: int
    avg_job_duration: float | None = None
    overall_status: str


class DashboardResponse(BaseModel):
    stats: JobStatsResponse
    active_jobs: list[JobResponse]
    recent_failures: list[JobResponse]
    time_range_hours: int


# ==================== ENDPOINTS ====================


@router.get("/health")
async def get_system_health(
    session: SessionDep,
    _user: AdminUser,
) -> SystemHealthResponse:
    """Get overall system health status (admin only)."""
    service = MonitoringService(session)
    health = await service.get_system_health()

    return SystemHealthResponse(
        rabbitmq_connected=health.rabbitmq_connected,
        database_connected=health.database_connected,
        queues=[
            QueueHealthResponse(
                name=q.name,
                messages_ready=q.messages_ready,
                messages_unacked=q.messages_unacked,
                consumers=q.consumers,
                is_healthy=q.is_healthy,
                warning=q.warning,
            )
            for q in health.queues
        ],
        active_jobs=health.active_jobs,
        failed_jobs_24h=health.failed_jobs_24h,
        avg_job_duration=health.avg_job_duration,
        overall_status=health.overall_status,
    )


@router.get("/dashboard")
async def get_admin_dashboard(
    session: SessionDep,
    _user: AdminUser,
    hours: int = 24,
) -> DashboardResponse:
    """Get monitoring dashboard data for all users (admin only)."""
    service = MonitoringService(session)
    data = service.get_job_dashboard_data(user_id=None, hours=hours)

    return DashboardResponse(
        stats=JobStatsResponse(**data["stats"]),
        active_jobs=data["active_jobs"],
        recent_failures=data["recent_failures"],
        time_range_hours=data["time_range_hours"],
    )


@router.get("/jobs")
async def list_all_jobs(
    session: SessionDep,
    _user: AdminUser,
    job_type: str | None = None,
    status: str | None = None,
    user_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List all jobs with optional filters (admin only)."""
    job_repo = JobRepository(session)

    jt = JobType(job_type) if job_type else None
    js = JobStatus(status) if status else None
    uid = UUID(user_id) if user_id else None

    if uid:
        jobs = job_repo.get_by_user(
            user_id=uid,
            job_type=jt,
            status=js,
            skip=skip,
            limit=limit,
        )
    else:
        jobs = job_repo.get_all_jobs(
            job_type=jt,
            status=js,
            skip=skip,
            limit=limit,
        )

    service = MonitoringService(session)
    return service.jobs_to_dicts(jobs)


def _job_file_to_response(jf: JobFile) -> JobFileResponse:
    return JobFileResponse(
        id=str(jf.id),
        external_file_id=jf.external_file_id,
        filename=jf.filename,
        state=jf.state,
        error_message=jf.error_message,
        error_detail=jf.error_detail,
        error_code=jf.error_code,
        created_at=jf.created_at.isoformat(),
        updated_at=jf.updated_at.isoformat(),
    )


@router.get("/jobs/{job_id}")
async def get_job_details(
    job_id: str,
    session: SessionDep,
    _user: AdminUser,
) -> dict[str, Any]:
    """Get detailed job information including events and per-file progress (admin only)."""
    job_repo = JobRepository(session)

    try:
        job_uuid = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    job = job_repo.get(job_uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    events = job_repo.get_job_events(job_uuid)
    files = job_repo.get_job_files(job_uuid)
    service = MonitoringService(session)

    job_dict = service._job_to_dict(job)
    job_dict["events"] = [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "old_status": e.old_status,
            "new_status": e.new_status,
            "message": e.message,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]
    job_dict["files"] = [_job_file_to_response(f).model_dump() for f in files]
    job_dict["input_params"] = job.input_params
    job_dict["result_summary"] = job.result_summary
    job_dict["error_details"] = job.error_details

    return job_dict


@router.get("/jobs/{job_id}/files")
async def get_job_files(
    job_id: str,
    session: SessionDep,
    _user: AdminUser,
) -> list[JobFileResponse]:
    """Per-file progress detail for a job (admin only).

    Lightweight endpoint for polling. Returns only the JobFile rows,
    without the event log, input params, or result summary that
    ``GET /jobs/{job_id}`` carries.
    """
    job_repo = JobRepository(session)

    try:
        job_uuid = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    if not job_repo.get(job_uuid):
        raise HTTPException(status_code=404, detail="Job not found")

    return [_job_file_to_response(f) for f in job_repo.get_job_files(job_uuid)]


@router.get("/jobs/by-knowledge-base/{kb_id}")
async def get_jobs_by_knowledge_base(
    kb_id: str,
    session: SessionDep,
    _user: AdminUser,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Get jobs related to a specific knowledge base (admin only)."""
    job_repo = JobRepository(session)

    try:
        kb_uuid = UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid knowledge base ID format")

    js = JobStatus(status) if status else None
    jobs = job_repo.find_by_entity(knowledge_base_id=kb_uuid, status=js)

    service = MonitoringService(session)
    return service.jobs_to_dicts(jobs)


@router.get("/jobs/by-datasource/{datasource_id}")
async def get_jobs_by_datasource(
    datasource_id: str,
    session: SessionDep,
    _user: AdminUser,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Get jobs related to a specific datasource (admin only)."""
    job_repo = JobRepository(session)

    try:
        ds_uuid = UUID(datasource_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datasource ID format")

    js = JobStatus(status) if status else None
    jobs = job_repo.find_by_entity(datasource_id=ds_uuid, status=js)

    service = MonitoringService(session)
    return service.jobs_to_dicts(jobs)


@router.get("/stats")
async def get_job_stats(
    session: SessionDep,
    _user: AdminUser,
    hours: int = 24,
) -> JobStatsResponse:
    """Get aggregated job statistics (admin only)."""
    job_repo = JobRepository(session)
    stats = job_repo.get_job_stats(hours=hours, user_id=None)
    return JobStatsResponse(**stats)


@router.post("/cleanup")
async def cleanup_old_jobs(
    session: SessionDep,
    _user: AdminUser,
    days: int = 30,
) -> dict[str, Any]:
    """Clean up old completed/failed jobs (admin only)."""
    job_repo = JobRepository(session)
    deleted_count = job_repo.cleanup_old_jobs(days=days)

    return {
        "message": f"Cleaned up {deleted_count} old jobs",
        "deleted_count": deleted_count,
        "retention_days": days,
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    session: SessionDep,
    _user: AdminUser,
) -> dict[str, Any]:
    """Cancel a pending job (admin only)."""
    job_repo = JobRepository(session)

    try:
        job_uuid = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    job = job_repo.get(job_uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in [JobStatus.PENDING.value, JobStatus.RUNNING.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status: {job.status}",
        )

    job_repo.fail_job(
        job_uuid,
        error_message="Job cancelled by administrator",
    )

    job.status = JobStatus.CANCELLED.value
    session.commit()

    return {
        "message": "Job cancelled successfully",
        "job_id": job_id,
        "status": JobStatus.CANCELLED.value,
    }


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: str,
    session: SessionDep,
    _user: AdminUser,
) -> dict[str, Any]:
    """Mark a failed job for retry by resetting its status to pending.

    Doesn't re-publish the job to the queue, the operation must be
    triggered again through the normal flow.
    """
    job_repo = JobRepository(session)

    try:
        job_uuid = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    job = job_repo.get(job_uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.FAILED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Can only retry failed jobs. Current status: {job.status}",
        )

    job.status = JobStatus.PENDING.value
    job.started_at = None
    job.completed_at = None
    job.error_message = None
    job.error_details = None
    job.retry_count += 1
    session.commit()

    job_repo._log_event(
        job_uuid,
        "retry",
        old_status=JobStatus.FAILED.value,
        new_status=JobStatus.PENDING.value,
        message=f"Retry #{job.retry_count} initiated by admin",
    )

    return {
        "message": "Job reset for retry",
        "job_id": job_id,
        "retry_count": job.retry_count,
        "status": JobStatus.PENDING.value,
    }
