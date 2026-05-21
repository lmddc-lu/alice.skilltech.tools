import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal, TypedDict

import httpx
import requests
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.models.enums import KnowledgeBaseStatus
from app.models.tables import Chatbot, KnowledgeBase
from app.services.persona_service import get_persona_for_chatbot


class HayhooksMessage(TypedDict):
    """Chat message shape sent over HTTP to Hayhooks.

    Wire contract, not the DB model (app.models.ChatMessage).
    """

    role: Literal["user", "assistant", "system"]
    content: str


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# cap concurrent Haystack inference requests; excess waits in queue
HAYSTACK_INFERENCE_SEMAPHORE = asyncio.Semaphore(4)


async def check_collection_exists(index_name: str) -> bool:
    """Check if a collection exists in Hayhooks."""
    api_url = f"{settings.HAYSTACK_INGESTION_URL}/document_management/run"
    headers = {"Content-Type": "application/json"}

    payload = {"action": "stats", "index_name": index_name}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                api_url, headers=headers, json=payload, timeout=10.0
            )
            response.raise_for_status()

            data = response.json()
            logger.info(f"{str(data)}")
            exists: bool = bool(data.get("result", {}).get("success", False))

            logger.info(f"Collection '{index_name}' exists: {exists}")
            return exists

    except httpx.TimeoutException:
        logger.error(f"Timeout checking collection '{index_name}'")
        return False
    except httpx.ConnectError:
        logger.error("Could not connect to Hayhooks service")
        raise HTTPException(
            status_code=503, detail="Could not connect to Hayhooks service"
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"Hayhooks API error during health check: {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking collection: {str(e)}")
        return False


async def validate_collection_before_query(index_name: str) -> None:
    """Raises HTTPException 404 if the collection doesn't exist."""
    exists = await check_collection_exists(index_name)

    if not exists:
        error_msg = f"Collection '{index_name}' does not exist. "
        logger.error(error_msg)
        raise HTTPException(status_code=404, detail=error_msg)


async def _fetch_file_content(
    index_name: str, file_id: str | None = None, file_name: str | None = None
) -> dict[str, Any] | None:
    """Fetch file content from hayhooks by file_id (preferred) or file_name. Returns None on not-found."""
    api_url = f"{settings.HAYSTACK_INGESTION_URL}/document_management/run"
    headers = {"Content-Type": "application/json"}
    payload = {
        "action": "get_file_content",
        "index_name": index_name,
    }
    if file_id:
        payload["file_id"] = file_id
    if file_name:
        payload["file_name"] = file_name

    async with httpx.AsyncClient() as client:
        response = await client.post(
            api_url, headers=headers, json=payload, timeout=30.0
        )
        response.raise_for_status()

        data = response.json()
        result = data.get("result", {})

        if not result.get("success"):
            return None

        return {
            "file_name": result.get("file_name", file_name or ""),
            "total_chunks": result.get("total_chunks", 0),
            "content": result.get("content", ""),
        }


async def get_file_parsed_content(
    index_name: str,
    file_name: str,
    stored_filename: str | None = None,  # noqa: ARG001
    file_id: str | None = None,
) -> dict[str, Any]:
    """Return parsed text of a file from its chunks in Qdrant.

    Looks up by file_id (preferred) with file_name as fallback. Returns
    a dict with file_name, total_chunks, and content.
    """
    lookup_label = file_id or file_name
    try:
        result = await _fetch_file_content(
            index_name, file_id=file_id, file_name=file_name
        )
        if result:
            result["file_name"] = file_name or file_id
            return result

        logger.warning(
            "No documents found: index=%s, file_id=%s, file_name=%s",
            index_name,
            file_id,
            file_name,
        )
        raise HTTPException(
            status_code=404,
            detail=f"No documents found for: {lookup_label}",
        )

    except httpx.TimeoutException:
        logger.error(f"Timeout retrieving parsed content for '{lookup_label}'")
        raise HTTPException(status_code=504, detail="Request to Hayhooks timed out")
    except httpx.ConnectError:
        logger.error("Could not connect to Hayhooks for file content retrieval")
        raise HTTPException(
            status_code=503, detail="Could not connect to Hayhooks service"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving parsed content for '{lookup_label}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def chat_with_hayhooks_stream(
    index_name: str,
    conversation_history: list[HayhooksMessage] | None = None,
    top_k: int = 5,
    persona: str | None = None,
    source_doc_token: str | None = None,
    skip_validation: bool = False,
    cite_sources: bool = True,
) -> AsyncIterator[bytes]:
    """Stream a response from the Hayhooks RAG pipeline."""
    if not skip_validation:
        await validate_collection_before_query(index_name)

    api_url = f"{settings.HAYSTACK_INFERENCE_URL}/chat/completions"
    headers = {"Content-Type": "application/json"}

    payload = {
        "model": "rag_query",
        "stream": True,
        "index_name": index_name,
        "messages": conversation_history,
        "top_k": top_k,
        "system_prompt": persona,
        "custom_id": source_doc_token if source_doc_token else "empty",
        "cite_sources": cite_sources,
    }

    try:
        async with HAYSTACK_INFERENCE_SEMAPHORE:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST", api_url, headers=headers, json=payload, timeout=120.0
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line:
                            yield line.encode() + b"\n"

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Request to Hayhooks timed out")
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503, detail="Could not connect to Hayhooks service"
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"Hayhooks API error: {e.response.text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Hayhooks API error: {e.response.text}",
        )
    except Exception as e:
        logger.error(f"Unexpected error calling Hayhooks: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def get_session_sources(session_id: str) -> list[dict[str, Any]]:
    """Fetch sources from hayhooks session_manager after streaming completes.

    session_id is the custom_id from the streaming request. Returns
    dicts with file_name, chunk_index, total_chunks, headings.
    """
    api_url = f"{settings.HAYSTACK_INFERENCE_URL}/session_manager/run"
    headers = {"Content-Type": "application/json"}
    payload = {"action": "get_sources", "session_id": session_id}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                api_url, headers=headers, json=payload, timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("result", {})
            sources: list[dict[str, Any]] = result.get("sources", [])
            return sources
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching sources for session {session_id}")
        return []
    except httpx.ConnectError:
        logger.error("Could not connect to Hayhooks for source retrieval")
        return []
    except Exception as e:
        logger.error(f"Error fetching sources for session {session_id}: {e}")
        return []


def delete_knowledge_by_local_id(local_kb_id: str) -> bool:
    api_url = f"{settings.HAYSTACK_INGESTION_URL}/document_management/run"
    headers = {"Content-Type": "application/json"}
    payload = {
        "action": "delete",
        "index_name": str(local_kb_id),
        "confirm_index_deletion": True,
    }

    logger.info(f"Sending request to Hayhooks: {api_url}")
    logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        hayhooks_result = response.json()

        logger.info(f"Knowledge base {local_kb_id} deleted: {hayhooks_result}")
    except Exception as e:
        logger.error(f"Error deleting knowledge base: {e}")
        return False

    return True


async def chat_with_knowledgebase_stream(
    messages: list[HayhooksMessage],
    knowledgebase_id: str,
    chatbot: Chatbot,
    session: Session,
    source_doc_token: str | None = None,
) -> AsyncIterator[bytes]:
    """Stream a chat response using the chatbot's persona."""
    cite_sources = getattr(chatbot, "cite_sources", True)

    async for chunk in chat_with_kb_stream(
        messages, knowledgebase_id, chatbot, session, source_doc_token, cite_sources
    ):
        yield chunk


async def chat_with_kb_stream(
    messages: list[HayhooksMessage],
    knowledgebase_id: str,
    chatbot: Chatbot,
    session: Session,
    source_doc_token: str | None = None,
    cite_sources: bool = True,
) -> AsyncIterator[bytes]:
    """Yield streaming chunks for a local KB chat via Hayhooks."""
    statement = select(KnowledgeBase).where(KnowledgeBase.id == knowledgebase_id)
    knowledgebase = session.exec(statement).first()

    if not knowledgebase:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if knowledgebase.status != KnowledgeBaseStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=f"Knowledge base is not ready for querying. Current status: {knowledgebase.status}",
        )

    conversation_history = messages
    persona = get_persona_for_chatbot(chatbot)
    index_name = str(knowledgebase_id)

    # KB status was already checked above, skip the redundant Hayhooks
    # collection check; doing both doubles load under concurrency.
    async for chunk in chat_with_hayhooks_stream(
        index_name=index_name,
        conversation_history=conversation_history,
        persona=persona,
        source_doc_token=source_doc_token,
        skip_validation=True,
        cite_sources=cite_sources,
    ):
        yield chunk
