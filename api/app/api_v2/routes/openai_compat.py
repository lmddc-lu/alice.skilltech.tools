import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select
from starlette.responses import Response

from app.api_v2.deps import SessionDep
from app.core.rate_limit import limiter
from app.models.tables import Chatbot
from app.repositories.chatbot import ChatbotRepository
from app.services.citation_service import build_citations, fetch_and_encode_citations
from app.services.rag_service import (
    HayhooksMessage,
    chat_with_knowledgebase_stream,
    get_session_sources,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["openai_compat"])


class OpenAIChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class OpenAIChatRequest(BaseModel):
    messages: list[OpenAIChatMessage]
    model: str = "default"
    stream: bool = True


def _resolve_chatbot(session: Session, token: str) -> Chatbot:
    """Look up chatbot by API token, raising appropriate HTTP errors."""
    chatbot: Chatbot | None = session.exec(
        select(Chatbot).where(Chatbot.token == token)
    ).first()
    if not chatbot:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not chatbot.api_enabled:
        raise HTTPException(
            status_code=403, detail="API access is not enabled for this chatbot"
        )
    if not chatbot.enabled:
        raise HTTPException(status_code=403, detail="Chatbot is disabled")
    return chatbot


def _extract_bearer_token(authorization: str | None) -> str:
    """Extract token from 'Bearer <token>' header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401, detail="Invalid Authorization header format"
        )
    return parts[1]


@router.post("/v1/chat/completions")
@limiter.limit("30/minute")
async def chat_completions(
    request: Request,
    body: OpenAIChatRequest,
    session: SessionDep,
    authorization: str | None = Header(None),
) -> Response:
    token = _extract_bearer_token(authorization)
    chatbot = _resolve_chatbot(session, token)

    ChatbotRepository(session).increment_chat_request_count(chatbot.id)

    source_doc_token = f"alice-{uuid.uuid4()}"
    messages: list[HayhooksMessage] = [
        {"role": m.role, "content": m.content} for m in body.messages
    ]

    if body.stream:
        return _streaming_response(chatbot, messages, source_doc_token, session)

    result = await _non_streaming_response(chatbot, messages, source_doc_token, session)
    return JSONResponse(content=result)


def _streaming_response(
    chatbot: Chatbot,
    messages: list[HayhooksMessage],
    source_doc_token: str,
    session: Session,
) -> StreamingResponse:
    async def generate() -> AsyncGenerator[bytes]:
        collected_text = []
        stream = chat_with_knowledgebase_stream(
            messages=messages,
            knowledgebase_id=str(chatbot.knowledge_base_id),
            chatbot=chatbot,
            session=session,
            source_doc_token=source_doc_token,
        )
        async for chunk in stream:
            if chunk:
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

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _non_streaming_response(
    chatbot: Chatbot,
    messages: list[HayhooksMessage],
    source_doc_token: str,
    session: Session,
) -> dict[str, Any]:
    collected: list[str] = []
    stream = chat_with_knowledgebase_stream(
        messages=messages,
        knowledgebase_id=str(chatbot.knowledge_base_id),
        chatbot=chatbot,
        session=session,
        source_doc_token=source_doc_token,
    )
    async for chunk in stream:
        if not chunk:
            continue
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
                    collected.append(content)
            except (json.JSONDecodeError, IndexError):
                pass

    full_content = "".join(collected)

    citations = []
    try:
        sources = await get_session_sources(source_doc_token)
        if sources:
            citations = build_citations(sources, full_content)
    except Exception as e:
        logger.error(f"Error fetching citations for non-streaming response: {e}")

    result: dict[str, Any] = {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": chatbot.name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": full_content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
    if citations:
        result["citations"] = citations
    return result
