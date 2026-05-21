"""Streaming chat endpoint for end-users interacting with a chatbot."""

import json
import logging
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api_v2.deps import OptionalUserDep, SessionDep
from app.core.rate_limit import limiter
from app.models.enums import KnowledgeBaseStatus
from app.repositories.chatbot import ChatbotRepository
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.services.access_service import AccessService
from app.services.citation_service import fetch_and_encode_citations
from app.services.rag_service import HayhooksMessage, chat_with_knowledgebase_stream

from .router import router
from .schemas import ChatRequest

logger = logging.getLogger(__name__)


@router.post("/chatbots/{chatbot_id}/chat/stream")
@limiter.limit("30/minute")
async def chat_with_chatbot_stream(
    request: Request,
    chatbot_id: str,
    req: ChatRequest,
    session: SessionDep,
    user: OptionalUserDep,
) -> StreamingResponse:
    """Stream chat with a chatbot."""
    chatbot_repo = ChatbotRepository(session)
    kb_repo = KnowledgeBaseRepository(session)

    chatbot = chatbot_repo.get(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.check_can_chat(chatbot, user, req.password)

    kb = kb_repo.get(chatbot.knowledge_base_id)
    if not kb:
        raise HTTPException(
            status_code=404, detail="Knowledge base not found for this chatbot"
        )

    if kb.status != KnowledgeBaseStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=f"Chatbot is not ready for chat. Status: {kb.status}",
        )

    for msg in req.messages:
        if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
            raise HTTPException(
                status_code=400,
                detail="Each message must have 'role' and 'content' fields",
            )
        if msg["role"] not in ["user", "assistant", "system"]:
            raise HTTPException(
                status_code=400,
                detail="Message role must be 'user', 'assistant', or 'system'",
            )

    chatbot_repo.increment_chat_request_count(chatbot.id)

    try:
        source_doc_token = f"alice-{uuid4()}"

        async def stream_response() -> AsyncIterator[bytes]:
            collected_text: list[str] = []
            stream_generator = chat_with_knowledgebase_stream(
                # roles/keys validated in the loop above, safe to narrow
                messages=cast(list[HayhooksMessage], req.messages),
                knowledgebase_id=str(chatbot.knowledge_base_id),
                chatbot=chatbot,
                session=session,
                source_doc_token=source_doc_token,
            )
            async for chunk in stream_generator:
                if chunk:
                    # collect content tokens so we know which citations to emit
                    text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                    for line in text.strip().split("\n"):
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[len("data:") :].strip()
                        if payload == "[DONE]":
                            continue
                        try:
                            parsed = json.loads(payload)
                            delta = parsed.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                collected_text.append(content)
                        except (json.JSONDecodeError, IndexError):
                            pass
                    yield chunk

            response_text = "".join(collected_text)
            citation_data = await fetch_and_encode_citations(
                source_doc_token, response_text
            )
            if citation_data:
                yield citation_data

        return StreamingResponse(stream_response(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Error streaming chat for chatbot {chatbot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
