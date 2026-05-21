import json
import logging
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue
from faststream.rabbit.fastapi import RabbitRouter
from sqlmodel import select

from app.api_v2.deps import SessionDep
from app.core.config import settings
from app.models.enums import JobStatus, JobType
from app.models.tables import Job
from app.repositories.job import JobRepository
from app.services.datasource_service import DatasourceService
from app.services.knowledgebase_service import KnowledgebaseService
from app.services.messaging_service import CANCEL_EXCHANGE

logger = logging.getLogger(__name__)

router = RabbitRouter(settings.RABBITMQ_URL, tags=["workers"])

metadata_sync_jobs_queue = RabbitQueue(name="metadata_sync_jobs", durable=True)
metadata_sync_completed_queue = RabbitQueue(
    name="metadata_sync_jobs_completed", durable=True
)
metadata_sync_failed_queue = RabbitQueue(name="metadata_sync_jobs_failed", durable=True)

content_sync_jobs_queue = RabbitQueue(name="content_sync_jobs", durable=True)
content_sync_completed_queue = RabbitQueue(
    name="content_sync_jobs_completed", durable=True
)
content_sync_failed_queue = RabbitQueue(name="content_sync_jobs_failed", durable=True)

ingestion_jobs_queue = RabbitQueue(name="ingestion_jobs", durable=True)
ingestion_completed_queue = RabbitQueue(name="ingestion_jobs_completed", durable=True)
ingestion_failed_queue = RabbitQueue(name="ingestion_jobs_failed", durable=True)

progress_update_queue = RabbitQueue(name="job_progress_updates", durable=True)

# workers bind exclusive queues to this fanout
cancel_exchange = RabbitExchange(
    name=CANCEL_EXCHANGE, type=ExchangeType.FANOUT, durable=True
)


@router.after_startup
async def startup(_app: FastAPI) -> None:
    """Declare all queues and exchanges on startup."""
    await router.broker.declare_queue(metadata_sync_jobs_queue)
    await router.broker.declare_queue(metadata_sync_completed_queue)
    await router.broker.declare_queue(metadata_sync_failed_queue)

    await router.broker.declare_queue(content_sync_jobs_queue)
    await router.broker.declare_queue(content_sync_completed_queue)
    await router.broker.declare_queue(content_sync_failed_queue)

    await router.broker.declare_queue(ingestion_jobs_queue)
    await router.broker.declare_queue(ingestion_completed_queue)
    await router.broker.declare_queue(ingestion_failed_queue)

    await router.broker.declare_queue(progress_update_queue)

    await router.broker.declare_exchange(cancel_exchange)

    logger.info("All job queues declared successfully")


def _get_job_id(message: dict[str, Any]) -> UUID | None:
    """Safely extract job_id from message."""
    job_id_str = message.get("job_id")
    if not job_id_str:
        return None
    try:
        return UUID(job_id_str)
    except (ValueError, TypeError):
        logger.warning(f"Invalid job_id in message: {job_id_str}")
        return None


def _complete_job(
    session: SessionDep,
    message: dict[str, Any],
    result_summary: dict[str, Any] | None = None,
) -> Job | None:
    """Mark a job as completed if job_id is present. Returns the Job or None."""
    job_id = _get_job_id(message)
    if not job_id:
        return None

    try:
        job_repo = JobRepository(session)
        job = job_repo.complete_job(job_id, result_summary=result_summary)
        if job:
            logger.info(f"Job {job_id} marked as completed")
        return job
    except Exception as e:
        logger.error(f"Failed to mark job {job_id} as completed: {e}")
        return None


def _fail_job(
    session: SessionDep,
    message: dict[str, Any],
    default_error: str = "Unknown error",
) -> Job | None:
    """Mark a job as failed if job_id is present. Returns the Job or None."""
    job_id = _get_job_id(message)
    if not job_id:
        return None

    try:
        job_repo = JobRepository(session)
        job = job_repo.fail_job(
            job_id,
            error_message=message.get("error", default_error),
            error_details=message.get("traceback") or message.get("error_details"),
        )
        if job:
            logger.info(f"Job {job_id} marked as failed")
        return job
    except Exception as e:
        logger.error(f"Failed to mark job {job_id} as failed: {e}")
        return None


def _start_job(session: SessionDep, message: dict[str, Any]) -> None:
    """Mark a job as started if job_id is present."""
    job_id = _get_job_id(message)
    if not job_id:
        return

    try:
        job_repo = JobRepository(session)
        job_repo.start_job(job_id)
        logger.info(f"Job {job_id} marked as started")
    except Exception as e:
        logger.error(f"Failed to mark job {job_id} as started: {e}")


async def _maybe_fire_deferred_ingestion(
    session: SessionDep, datasource_id: str | None
) -> None:
    """Advance any reindex job that's waiting on this datasource's metadata.

    `IndexingService.trigger_reindex` defers ingestion when a KB has Moodle
    datasources by parking the prepared sync payload and a waiting list on
    the ingestion job's `input_params`. Each metadata-sync completion (or
    failure) decrements the waiting list; the last one fires the parked
    payload onto the ingestion queue. Failures still chain forward,
    ingestion fetches fresh data from Moodle directly, so a stale cache is
    a degradation, not a blocker.
    """
    if not datasource_id:
        return

    statement = select(Job).where(
        Job.status == JobStatus.PENDING.value,
        Job.job_type == JobType.INGESTION.value,
    )
    pending_ingestions = list(session.exec(statement))

    for job in pending_ingestions:
        if not job.input_params:
            continue
        try:
            params = json.loads(job.input_params)
        except json.JSONDecodeError:
            continue

        deferred = params.get("deferred_ingestion")
        if not isinstance(deferred, dict):
            continue

        waiting = deferred.get("waiting_for_datasources") or []
        if datasource_id not in waiting:
            continue

        waiting = [d for d in waiting if d != datasource_id]

        if waiting:
            deferred["waiting_for_datasources"] = waiting
            params["deferred_ingestion"] = deferred
            job.input_params = json.dumps(params)
            session.commit()
            logger.info(
                f"Reindex job {job.id} still waiting on {len(waiting)} datasource(s)"
            )
            continue

        sync_job = deferred.get("sync_job")
        if not isinstance(sync_job, dict):
            logger.error(
                f"Reindex job {job.id} has empty deferred sync_job; "
                f"skipping ingestion fan-out"
            )
            params.pop("deferred_ingestion", None)
            job.input_params = json.dumps(params)
            session.commit()
            continue

        # all metadata syncs in. clear deferred state and publish before
        # logging so the row is consistent if the publish raises.
        params.pop("deferred_ingestion", None)
        job.input_params = json.dumps(params)
        session.commit()

        try:
            await router.broker.publish(
                json.dumps(sync_job),
                routing_key="ingestion_jobs",
            )
            logger.info(
                f"Reindex job {job.id} metadata phase complete; fired ingestion"
            )
        except Exception as e:
            logger.error(f"Failed to publish deferred ingestion for job {job.id}: {e}")
            job_repo = JobRepository(session)
            job_repo.fail_job(
                job.id,
                error_message=f"Failed to publish deferred ingestion: {e}",
            )


@router.subscriber(progress_update_queue)
async def handle_progress_update(message: dict[str, Any], session: SessionDep) -> None:
    """Handle progress updates from workers.

    Any message (with or without a ``file``) bumps ``progress_updated_at``
    on the job so stale detection treats it as alive.
    """
    job_id = _get_job_id(message)
    if not job_id:
        logger.warning("Progress update received without job_id")
        return

    try:
        job_repo = JobRepository(session)
        job_repo.update_progress(
            job_id=job_id,
            message=message.get("message"),
            total_files=message.get("total_files"),
            file=message.get("file"),
        )
        file_info = message.get("file")
        if file_info:
            logger.debug(
                f"Job {job_id} file {file_info.get('external_file_id')}: "
                f"{file_info.get('state')}"
            )
        else:
            logger.debug(f"Job {job_id} progress: {message.get('message')}")
    except Exception as e:
        logger.error(f"Failed to update progress for job {job_id}: {e}")


@router.subscriber(metadata_sync_completed_queue)
async def metadata_sync_complete(message: dict[str, Any], session: SessionDep) -> None:
    """Handle completed metadata sync jobs."""
    logger.info(
        f"Metadata sync completed for datasource {message.get('datasource_id')}"
    )

    courses = message.get("courses", [])
    result_summary = {
        "courses_synced": len(courses),
        "datasource_id": message.get("datasource_id"),
    }

    _complete_job(session, message, result_summary=result_summary)

    DatasourceService(session).handle_metadata_sync_completion(message)

    await _maybe_fire_deferred_ingestion(session, message.get("datasource_id"))


@router.subscriber(metadata_sync_failed_queue)
async def metadata_sync_failed(message: dict[str, Any], session: SessionDep) -> None:
    """Handle failed metadata sync jobs."""
    logger.warning(
        f"Metadata sync failed for datasource {message.get('datasource_id')}: "
        f"{message.get('error')}"
    )

    _fail_job(session, message, default_error="Metadata sync failed")

    DatasourceService(session).handle_metadata_sync_failure(message)

    # a failed cache refresh shouldn't block ingestion, the worker fetches
    # fresh data from Moodle directly anyway. chain the deferred ingestion
    # forward as if the metadata sync had succeeded.
    await _maybe_fire_deferred_ingestion(session, message.get("datasource_id"))


@router.subscriber(content_sync_completed_queue)
async def content_sync_complete(message: dict[str, Any], session: SessionDep) -> None:
    """Handle completed content sync jobs."""
    logger.info(
        f"Content sync completed for datasource {message.get('datasource_id')}: "
        f"{message.get('files_downloaded', 0)} files downloaded"
    )

    result_summary = {
        "files_downloaded": message.get("files_downloaded", 0),
        "total_size_bytes": message.get("total_size_bytes", 0),
        "datasource_id": message.get("datasource_id"),
    }

    _complete_job(session, message, result_summary=result_summary)

    DatasourceService(session).handle_content_sync_completion(message)


@router.subscriber(content_sync_failed_queue)
async def content_sync_failed(message: dict[str, Any], session: SessionDep) -> None:
    """Handle failed content sync jobs."""
    logger.warning(
        f"Content sync failed for datasource {message.get('datasource_id')}: "
        f"{message.get('error')} (downloaded {message.get('files_downloaded', 0)} files)"
    )

    _fail_job(session, message, default_error="Content sync failed")

    DatasourceService(session).handle_content_sync_failure(message)


@router.subscriber(ingestion_completed_queue)
async def kb_sync_complete(message: dict[str, Any], session: SessionDep) -> None:
    """Handle completed knowledge base ingestion jobs."""
    files_succeeded = message.get("files_succeeded", message.get("files_processed", 0))
    files_failed = message.get("files_failed", 0)
    logger.info(
        f"KB ingestion completed for {message.get('knowledge_base_id')}: "
        f"{files_succeeded} succeeded, {files_failed} failed, "
        f"{message.get('chunks_created', 0)} chunks created"
    )

    result_summary = {
        "knowledge_base_id": message.get("knowledge_base_id"),
        "files_processed": message.get("files_processed", 0),
        "files_succeeded": files_succeeded,
        "files_failed": files_failed,
        "failed_files": message.get("failed_files", []),
        "files_downloaded": message.get("files_downloaded", 0),
        "chunks_created": message.get("chunks_created", 0),
        "embedding_time_seconds": message.get("embedding_time_seconds"),
    }

    # _complete_job returns None for cancelled jobs. a cancelled job means
    # a new ingestion was triggered with updated files, so skip the KB
    # status update.
    job = _complete_job(session, message, result_summary=result_summary)

    if job is not None:
        KnowledgebaseService(session).handle_knowledgebase_sync_completion(message)
    else:
        logger.info(
            f"Skipping KB status update for cancelled/unknown job "
            f"(KB={message.get('knowledge_base_id')})"
        )


@router.subscriber(ingestion_failed_queue)
async def kb_sync_failed(message: dict[str, Any], session: SessionDep) -> None:
    """Handle failed knowledge base ingestion jobs."""
    logger.warning(
        f"KB ingestion failed for {message.get('knowledge_base_id')}: "
        f"{message.get('error')}"
    )

    # None means the job was cancelled, skip KB status update
    job = _fail_job(session, message, default_error="Knowledge base ingestion failed")

    if job is not None:
        KnowledgebaseService(session).handle_knowledgebase_sync_failure(message)
    else:
        logger.info(
            f"Skipping KB failure update for cancelled/unknown job "
            f"(KB={message.get('knowledge_base_id')})"
        )
