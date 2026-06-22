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
from app.repositories.user import UserRepository
from app.services.access_service import AccessService
from app.services.citation_service import fetch_chat_trailer_events
from app.services.index_manifest import enforce_index_freshness
from app.services.pii_filter_service import StreamUnredactor
from app.services.rag_service import HayhooksMessage, chat_with_knowledgebase_stream

from .router import router
from .schemas import ChatRequest

logger = logging.getLogger(__name__)


def _content_event(content: str) -> str:
    """Build a minimal OpenAI-style SSE data line carrying a content delta.

    Used to emit any text the unredactor was still holding when the stream
    ends, so the final placeholder doesn't get dropped."""
    payload = {"choices": [{"index": 0, "delta": {"content": content}}]}
    return "data: " + json.dumps(payload, ensure_ascii=False)


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

    # Owners and platform admins can request an extra `debug_chunks` SSE event
    # exposing the exact chunks retrieved for the answer (debugging retrieval
    # quality). Opt-in via req.debug, only the editor preview window sets it, so
    # the public chat page never surfaces it even for owners/admins.
    can_debug_chunks = bool(
        req.debug
        and user
        and (chatbot.owner_id == user.id or UserRepository(session).is_admin(user))
    )

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

    # Detect index drift (embedding/sparse config changed since this KB was built).
    enforce_index_freshness(kb)

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

        # When the PII filter is on, the redaction map is populated by the
        # stream generator before its first chunk; we then swap placeholders in
        # the LLM's response back to the user's original text.
        pii_enabled = bool(getattr(chatbot, "pii_filter_enabled", False))
        pii_map: dict[str, str] = {}

        async def stream_response() -> AsyncIterator[bytes]:
            collected_text: list[str] = []
            # Emitted once, the first time we observe that real PII was redacted
            # from this exchange, so the client can warn the user.
            pii_notice_sent = False
            unredactor = StreamUnredactor(pii_map)
            stream_generator = chat_with_knowledgebase_stream(
                # roles/keys validated in the loop above, safe to narrow
                messages=cast(list[HayhooksMessage], req.messages),
                knowledgebase_id=str(chatbot.knowledge_base_id),
                chatbot=chatbot,
                session=session,
                source_doc_token=source_doc_token,
                pii_unredact_map=pii_map if pii_enabled else None,
            )
            async for chunk in stream_generator:
                if not chunk:
                    continue
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk

                # The redaction map is filled before the first chunk; a non-empty
                # map means actual personal data was stripped from the user's
                # message. Tell the client once so it can surface a warning.
                if pii_enabled and pii_map and not pii_notice_sent:
                    pii_notice_sent = True
                    yield b'data: {"pii_filtered": true}\n'

                if not pii_enabled:
                    # Fast path: collect content tokens for citations, pass through.
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
                    continue

                # PII path: rewrite each content delta through the unredactor.
                out = ""
                for raw_line in text.split("\n"):
                    line = raw_line.strip()
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        out += raw_line + "\n"
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        tail = unredactor.flush()
                        if tail:
                            collected_text.append(tail)
                            out += _content_event(tail) + "\n"
                        out += "data: [DONE]\n"
                        continue
                    try:
                        parsed = json.loads(payload)
                        delta = parsed.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                    except (json.JSONDecodeError, IndexError):
                        out += raw_line + "\n"
                        continue
                    if content:
                        emitted = unredactor.feed(content)
                        delta["content"] = emitted
                        collected_text.append(emitted)
                        out += "data: " + json.dumps(parsed, ensure_ascii=False) + "\n"
                    else:
                        out += raw_line + "\n"
                if out:
                    yield out.encode("utf-8")

            # If the upstream ended without a [DONE], flush any held placeholder.
            tail = unredactor.flush()
            if tail:
                collected_text.append(tail)
                yield (_content_event(tail) + "\n").encode("utf-8")

            if pii_enabled and unredactor.restored:
                # Log placeholder keys only
                logger.info(
                    "PII unredaction: restored %d placeholder(s) in response %s",
                    len(unredactor.restored),
                    sorted(unredactor.restored),
                )

            response_text = "".join(collected_text)
            for event in await fetch_chat_trailer_events(
                source_doc_token,
                response_text,
                include_debug_chunks=can_debug_chunks,
            ):
                yield event

        return StreamingResponse(stream_response(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Error streaming chat for chatbot {chatbot_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
