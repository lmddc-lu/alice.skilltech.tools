"""Read-only listing and access-gate endpoints for chatbots.

- ``GET  /chatbots``: owner's chatbot list
- ``GET  /chatbots/{id}/details``: owner-only detailed view
- ``GET  /chatbots/{id}/info``: public access-requirements probe
- ``POST /chatbots/{id}/access``: verify access and return public view
"""

import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.api_v2.deps import (
    ChatbotServiceDep,
    OptionalUserDep,
    SessionDep,
    UserDep,
)
from app.core.storage import build_chatbot_avatar_url
from app.models.enums import ChatbotPersonaType, KnowledgeBaseStatus
from app.models.schemas import (
    ChatbotResponse,
    DetailedChatbotResponse,
    PublicChatbotResponse,
)
from app.repositories.chatbot import ChatbotRepository
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.services.access_service import AccessService

from .router import router
from .schemas import ChatbotAccessRequest


@router.get("/chatbots")
def get_chatbots(
    session: SessionDep,
    user: UserDep,
    skip: int = 0,
    limit: int = 100,
) -> list[ChatbotResponse]:
    """Get user's chatbots."""
    chatbot_repo = ChatbotRepository(session)
    kb_repo = KnowledgeBaseRepository(session)
    chatbots = chatbot_repo.get_by_owner(user.id, skip=skip, limit=limit)
    results = []
    for chatbot in chatbots:
        data = chatbot.model_dump()
        kb = kb_repo.get(chatbot.knowledge_base_id)
        data["status"] = kb.status if kb else KnowledgeBaseStatus.READY
        results.append(ChatbotResponse(**data))
    return results


@router.get("/chatbots/{chatbot_id}/details")
def get_chatbot(
    chatbot_id: str,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
) -> DetailedChatbotResponse:
    """Get a specific chatbot with detailed information (owner only)."""
    chatbot = chatbot_service.get_chatbot(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)
    return chatbot_service.build_detailed_response(chatbot)


@router.get("/chatbots/{chatbot_id}/info")
def get_chatbot_info(
    session: SessionDep,
    chatbot_id: str,
) -> dict[str, Any]:
    """Public probe for chatbot access requirements. No auth required."""
    try:
        UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    chatbot_repo = ChatbotRepository(session)
    chatbot = chatbot_repo.get(UUID(chatbot_id))

    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    kb_repo = KnowledgeBaseRepository(session)
    kb = kb_repo.get(chatbot.knowledge_base_id)
    kb_status = kb.status if kb else KnowledgeBaseStatus.ERROR

    return {
        "id": str(chatbot.id),
        "access_level": chatbot.access_level,
        "enabled": chatbot.enabled,
        "status": kb_status,
    }


@router.post("/chatbots/{chatbot_id}/access")
def get_chatbot_public(
    session: SessionDep,
    chatbot_id: str,
    user: OptionalUserDep,
    access_request: ChatbotAccessRequest,
) -> PublicChatbotResponse:
    """Get full chatbot details after access verification.

    Access levels:
    - public: anyone can access
    - password: requires correct password in request body
    - private: requires authentication and ownership
    """
    try:
        chatbot_uuid = UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    chatbot_repo = ChatbotRepository(session)
    kb_repo = KnowledgeBaseRepository(session)

    chatbot = chatbot_repo.get(chatbot_uuid)
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_access(chatbot, user, access_request.password)

    kb = kb_repo.get(chatbot.knowledge_base_id)
    kb_status = kb.status if kb else "unknown"

    prompt_suggestions = None
    if chatbot.prompt_suggestions:
        try:
            parsed = json.loads(chatbot.prompt_suggestions)
            if isinstance(parsed, list):
                prompt_suggestions = [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass

    avatar_url = build_chatbot_avatar_url(chatbot.id, chatbot.avatar_storage_path)

    return PublicChatbotResponse(
        id=chatbot.id,
        name=chatbot.name,
        description=chatbot.description,
        status=kb_status,
        enabled=chatbot.enabled,
        access_level=chatbot.access_level,
        personaType=ChatbotPersonaType(chatbot.personaType),
        prompt_suggestions=prompt_suggestions,
        avatar_url=avatar_url,
        persist_session=chatbot.persist_session,
    )
