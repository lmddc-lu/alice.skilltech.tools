"""Indexing-job control endpoints: trigger, cancel, and inspect status."""

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.api_v2.deps import SessionDep, UserDep
from app.models.enums import KnowledgeBaseStatus, ReindexFrequency, SyncErrorCode
from app.repositories.chatbot import ChatbotRepository
from app.repositories.job import JobRepository
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.services.access_service import AccessService
from app.services.indexing_service import IndexingService
from app.services.scheduler_service import scheduler_service

from .router import router
from .schemas import ReindexScheduleRequest, ReindexScheduleResponse

logger = logging.getLogger(__name__)


@router.post("/chatbots/{chatbot_id}/reindex")
async def reindex_chatbot(
    chatbot_id: str,
    session: SessionDep,
    user: UserDep,
    force: bool = False,
) -> dict[str, Any]:
    """Manually trigger re-indexing of a chatbot's knowledge base.

    Incremental by default (unchanged files are skipped); pass force=true
    to rebuild the collection from scratch.
    """
    chatbot_repo = ChatbotRepository(session)
    indexing_service = IndexingService(router.broker)

    chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    try:
        result = await indexing_service.trigger_reindex(
            session=session,
            knowledge_base_id=chatbot.knowledge_base_id,
            user=user,
            force=force,
            force_ocr=chatbot.force_ocr,
        )
        logger.info(f"Started manual re-indexing for chatbot {chatbot_id}")

        return {
            "message": "Re-indexing started successfully",
            "chatbot_id": str(chatbot.id),
            "job_id": result.get("job_id"),
            "status": KnowledgeBaseStatus.PROCESSING,
        }
    except Exception as e:
        logger.error(f"Failed to trigger re-indexing: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start re-indexing: {str(e)}"
        )


@router.post("/chatbots/{chatbot_id}/cancel-indexing")
async def cancel_chatbot_indexing(
    chatbot_id: str,
    session: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    """Cancel the active indexing job for a chatbot and set its status to error."""
    chatbot_repo = ChatbotRepository(session)
    indexing_service = IndexingService(router.broker)

    chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    kb_repo = KnowledgeBaseRepository(session)
    kb = kb_repo.get(chatbot.knowledge_base_id)
    if not kb or kb.status != KnowledgeBaseStatus.PROCESSING:
        raise HTTPException(
            status_code=409, detail="Chatbot is not currently processing"
        )

    job_repo = JobRepository(session)
    active_job = job_repo.get_active_for_knowledge_base(chatbot.knowledge_base_id)
    if active_job:
        await indexing_service.cancel_job(session, active_job.id)

    # set KB to error so the owner can retry later
    kb.status = KnowledgeBaseStatus.ERROR
    kb.last_sync_error = SyncErrorCode.CANCELLED
    session.commit()

    return {
        "message": "Indexing cancelled successfully",
        "chatbot_id": chatbot_id,
        "status": KnowledgeBaseStatus.ERROR,
    }


def _build_reindex_schedule_response(chatbot: Any) -> ReindexScheduleResponse:
    return ReindexScheduleResponse(
        chatbot_id=chatbot.id,
        enabled=chatbot.reindex_schedule_enabled,
        frequency=(
            ReindexFrequency(chatbot.reindex_schedule_frequency)
            if chatbot.reindex_schedule_frequency
            else None
        ),
        day_of_week=chatbot.reindex_schedule_day_of_week,
        day_of_month=chatbot.reindex_schedule_day_of_month,
        hour=chatbot.reindex_schedule_hour,
        minute=chatbot.reindex_schedule_minute,
    )


@router.get("/chatbots/{chatbot_id}/reindex-schedule")
def get_reindex_schedule(
    chatbot_id: str, session: SessionDep, user: UserDep
) -> ReindexScheduleResponse:
    """Return the current weekly reindex schedule for a chatbot."""
    chatbot_repo = ChatbotRepository(session)
    chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)
    return _build_reindex_schedule_response(chatbot)


@router.put("/chatbots/{chatbot_id}/reindex-schedule")
def set_reindex_schedule(
    chatbot_id: str,
    payload: ReindexScheduleRequest,
    session: SessionDep,
    user: UserDep,
) -> ReindexScheduleResponse:
    """Create, update, or disable a chatbot's reindex schedule.

    When ``enabled`` is True, ``frequency`` and ``hour`` are required;
    weekly also needs ``day_of_week``, monthly needs ``day_of_month``.
    """
    chatbot_repo = ChatbotRepository(session)
    chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    if payload.enabled:
        if payload.frequency is None or payload.hour is None:
            raise HTTPException(
                status_code=400,
                detail="frequency and hour are required when enabling a schedule",
            )
        if payload.frequency == ReindexFrequency.WEEKLY and payload.day_of_week is None:
            raise HTTPException(
                status_code=400,
                detail="day_of_week is required for weekly frequency",
            )
        if (
            payload.frequency == ReindexFrequency.MONTHLY
            and payload.day_of_month is None
        ):
            raise HTTPException(
                status_code=400,
                detail="day_of_month is required for monthly frequency",
            )
        # scheduled reindex only makes sense for remote sources that
        # can drift. file/free-text KBs are reingested on every edit.
        if not IndexingService._get_moodle_datasource_ids(
            session, chatbot.knowledge_base_id
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Scheduled reindex requires at least one Moodle datasource "
                    "on the chatbot's knowledge base"
                ),
            )
        chatbot.reindex_schedule_enabled = True
        chatbot.reindex_schedule_frequency = payload.frequency.value
        # clear the field that doesn't apply to the chosen frequency
        if payload.frequency == ReindexFrequency.WEEKLY:
            chatbot.reindex_schedule_day_of_week = payload.day_of_week
            chatbot.reindex_schedule_day_of_month = None
        else:
            chatbot.reindex_schedule_day_of_month = payload.day_of_month
            chatbot.reindex_schedule_day_of_week = None
        chatbot.reindex_schedule_hour = payload.hour
        chatbot.reindex_schedule_minute = payload.minute
    else:
        chatbot.reindex_schedule_enabled = False

    session.commit()
    session.refresh(chatbot)

    if chatbot.reindex_schedule_enabled:
        try:
            scheduler_service.schedule_chatbot_reindex(
                chatbot.id,
                frequency=chatbot.reindex_schedule_frequency,  # type: ignore[arg-type]
                hour=chatbot.reindex_schedule_hour,  # type: ignore[arg-type]
                minute=chatbot.reindex_schedule_minute,
                day_of_week=chatbot.reindex_schedule_day_of_week,
                day_of_month=chatbot.reindex_schedule_day_of_month,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        scheduler_service.unschedule_chatbot_reindex(chatbot.id)

    return _build_reindex_schedule_response(chatbot)


@router.delete("/chatbots/{chatbot_id}/reindex-schedule")
def delete_reindex_schedule(
    chatbot_id: str, session: SessionDep, user: UserDep
) -> ReindexScheduleResponse:
    """Disable a chatbot's weekly reindex schedule."""
    chatbot_repo = ChatbotRepository(session)
    chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    chatbot.reindex_schedule_enabled = False
    session.commit()
    session.refresh(chatbot)

    scheduler_service.unschedule_chatbot_reindex(chatbot.id)
    return _build_reindex_schedule_response(chatbot)


@router.get("/chatbots/{chatbot_id}/job-status")
def get_chatbot_job_status(
    chatbot_id: str, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    """Get the current job status for a chatbot's knowledge base."""
    chatbot_repo = ChatbotRepository(session)
    chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    job_repo = JobRepository(session)
    job = job_repo.get_latest_for_knowledge_base(chatbot.knowledge_base_id)

    if not job:
        kb_repo = KnowledgeBaseRepository(session)
        kb = kb_repo.get(chatbot.knowledge_base_id)
        return {
            "status": kb.status if kb else None,
            "progress": None,
            "files": [],
            "created_at": None,
            "started_at": None,
        }

    percentage = job_repo.get_progress_percentage(job)
    job_files = job_repo.get_job_files(job.id)
    deferred = job_repo.get_deferred_state(job)

    phase = "waiting_metadata" if deferred else None
    progress_message = job.progress_message
    if deferred and not progress_message:
        n = len(deferred["waiting_for_datasources"])
        progress_message = (
            f"Waiting on Moodle metadata refresh ({n} datasource"
            f"{'s' if n != 1 else ''})"
        )

    return {
        "status": job.status,
        "phase": phase,
        "progress": {
            "current": job.progress_current or 0,
            "total": job.progress_total or 0,
            "percentage": percentage,
            "message": progress_message,
        },
        "files": [
            {
                "id": str(jf.id),
                "external_file_id": jf.external_file_id,
                "filename": jf.filename,
                "state": jf.state,
                "error_message": jf.error_message,
                "error_code": jf.error_code,
                "created_at": jf.created_at.isoformat(),
                "updated_at": jf.updated_at.isoformat(),
            }
            for jf in job_files
        ],
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
    }
