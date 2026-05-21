"""Per-chatbot lifecycle endpoints: status, partial update, delete."""

import json
import logging
import uuid
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.api_v2.deps import (
    ChatbotServiceDep,
    KnowledgebaseServiceDep,
    SessionDep,
    UserDep,
)
from app.core.storage import StorageManager
from app.models.enums import KnowledgeBaseStatus
from app.models.schemas import DetailedChatbotResponse
from app.repositories.chatbot import ChatbotRepository
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.services.access_service import AccessService
from app.services.scheduler_service import scheduler_service

from .router import router
from .schemas import ChatbotUpdate

logger = logging.getLogger(__name__)


@router.get("/chatbots/{chatbot_id}/status")
def get_chatbot_status(
    chatbot_id: str, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    """Get the current status of a chatbot (including indexing progress)."""
    chatbot_repo = ChatbotRepository(session)
    kb_repo = KnowledgeBaseRepository(session)

    chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    kb = kb_repo.get(chatbot.knowledge_base_id)
    if not kb:
        raise HTTPException(
            status_code=404, detail="Knowledge base not found for this chatbot"
        )

    return {
        "chatbot_id": str(chatbot.id),
        "chatbot_name": chatbot.name,
        "status": kb.status,
        "last_sync": kb.last_sync.isoformat() if kb.last_sync else None,
        "last_sync_error": kb.last_sync_error,
        "is_ready": kb.status == KnowledgeBaseStatus.READY,
        "can_chat": kb.status == KnowledgeBaseStatus.READY,
    }


@router.patch("/chatbots/{chatbot_id}")
def update_chatbot(
    chatbot_id: str,
    chatbot_data: ChatbotUpdate,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
) -> DetailedChatbotResponse:
    """Update a chatbot's metadata (name, description, persona)."""
    chatbot_repo = ChatbotRepository(chatbot_service.session)

    existing_chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not existing_chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(existing_chatbot, user)

    update_data = chatbot_data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    if "password" in update_data and update_data["password"]:
        update_data["password_hash"] = AccessService.hash_password(
            update_data.pop("password")
        )
    elif "password" in update_data:
        update_data.pop("password")

    if "prompt_suggestions" in update_data:
        suggestions = update_data["prompt_suggestions"]
        if suggestions is not None:
            update_data["prompt_suggestions"] = json.dumps(suggestions)

    updated_chatbot = chatbot_repo.update_chatbot(
        chatbot_id=UUID(chatbot_id), chatbot_in=update_data
    )

    return chatbot_service.build_detailed_response(updated_chatbot)


@router.post("/chatbots/{chatbot_id}/rotate-token")
def rotate_chatbot_token(
    chatbot_id: str,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
) -> DetailedChatbotResponse:
    """Generate a fresh API token for a chatbot, invalidating the previous one."""
    chatbot_repo = ChatbotRepository(chatbot_service.session)

    existing_chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not existing_chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(existing_chatbot, user)

    new_token = str(uuid.uuid4()).replace("-", "")
    updated_chatbot = chatbot_repo.update_chatbot(
        chatbot_id=UUID(chatbot_id), chatbot_in={"token": new_token}
    )

    return chatbot_service.build_detailed_response(updated_chatbot)


@router.delete("/chatbots/{chatbot_id}")
def delete_chatbot(
    chatbot_id: str,
    session: SessionDep,
    user: UserDep,
    kb_service: KnowledgebaseServiceDep,
) -> dict[str, Any]:
    """Delete a chatbot and its associated knowledge base and datasource."""
    chatbot_repo = ChatbotRepository(session)

    chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    avatar_path = chatbot.avatar_storage_path
    kb_id = chatbot.knowledge_base_id
    scheduler_service.unschedule_chatbot_reindex(chatbot.id)
    # Chatbot.knowledge_base_id has a RESTRICT FK on KnowledgeBase, so the
    # chatbot row must be deleted before the KB
    chatbot_repo.delete_with_sessions(UUID(chatbot_id))

    if avatar_path:
        try:
            StorageManager().delete_file(avatar_path)
        except Exception as e:
            logger.warning(f"Failed to delete avatar {avatar_path}: {e}")

    try:
        kb_result = kb_service.delete_knowledgebase_with_validation(
            kb_id=str(kb_id), user=user
        )
        if kb_result.get("vector_index_error"):
            logger.warning(
                f"Vector index cleanup warning for KB {kb_id}: "
                f"{kb_result['vector_index_error']}"
            )
        if kb_result.get("s3_errors"):
            logger.warning(
                f"S3 cleanup errors for KB {kb_id}: {kb_result['s3_errors']}"
            )
        logger.info(f"Deleted chatbot {chatbot_id} and its knowledge base {kb_id}")
    except Exception as e:
        logger.error(f"Chatbot deleted but KB cleanup failed: {str(e)}")

    return {
        "message": "Chatbot deleted successfully",
        "chatbot_id": chatbot_id,
    }
