"""Chatbot avatar upload / retrieval / removal endpoints."""

import logging
import mimetypes
import os
import tempfile
from uuid import UUID, uuid4

from fastapi import File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api_v2.deps import ChatbotServiceDep, SessionDep, UserDep
from app.core.rate_limit import limiter
from app.core.storage import StorageManager, get_user_base_path
from app.models.schemas import DetailedChatbotResponse
from app.repositories.chatbot import ChatbotRepository
from app.services.access_service import AccessService

from .router import router

logger = logging.getLogger(__name__)


# GIFs excluded to avoid animated avatars in chat UI
_AVATAR_ALLOWED_MIME_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
_AVATAR_MAX_BYTES = 5 * 1024 * 1024


def _build_avatar_storage_path(
    user_email: str, chatbot_id: UUID, stored_filename: str
) -> str:
    return (
        f"{get_user_base_path(user_email)}/chatbots/{chatbot_id}/avatar/"
        f"{stored_filename}"
    )


@router.post("/chatbots/{chatbot_id}/avatar")
@limiter.limit("10/minute")
async def upload_chatbot_avatar(
    request: Request,
    chatbot_id: str,
    file: UploadFile = File(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user: UserDep = None,  # type: ignore[assignment]
    chatbot_service: ChatbotServiceDep = None,  # type: ignore[assignment]
) -> DetailedChatbotResponse:
    """Upload a custom avatar image for a chatbot.

    Overwrites any previous avatar. The old object is deleted only
    after the new one is stored, so the chatbot is never left without
    an avatar if upload succeeds.
    """
    try:
        chatbot_uuid = UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chatbot ID format")

    chatbot_repo = ChatbotRepository(session)
    chatbot = chatbot_repo.get(chatbot_uuid)
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")
    AccessService.verify_ownership(chatbot, user)

    extension = _AVATAR_ALLOWED_MIME_TYPES.get(file.content_type or "")
    if not extension:
        raise HTTPException(
            status_code=400,
            detail="Avatar must be a PNG, JPEG, or WebP image",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Avatar exceeds {_AVATAR_MAX_BYTES // (1024 * 1024)} MB limit",
        )

    storage = StorageManager()
    stored_filename = f"{uuid4().hex}{extension}"
    storage_path = _build_avatar_storage_path(
        user_email=user.email,
        chatbot_id=chatbot_uuid,
        stored_filename=stored_filename,
    )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=extension)
    try:
        tmp.write(content)
        tmp.close()
        uploaded = storage.upload_file(
            local_path=tmp.name,
            storage_path=storage_path,
            content_type=file.content_type or "application/octet-stream",
        )
        if not uploaded:
            raise HTTPException(status_code=500, detail="Failed to store avatar image")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    previous_path = chatbot.avatar_storage_path
    updated_chatbot = chatbot_repo.update_chatbot(
        chatbot_id=chatbot_uuid,
        chatbot_in={"avatar_storage_path": storage_path},
    )

    # best-effort cleanup, new avatar is already active
    if previous_path and previous_path != storage_path:
        try:
            storage.delete_file(previous_path)
        except Exception as e:
            logger.warning(f"Failed to delete previous avatar {previous_path}: {e}")

    return chatbot_service.build_detailed_response(updated_chatbot)


@router.delete("/chatbots/{chatbot_id}/avatar")
def delete_chatbot_avatar(
    chatbot_id: str,
    session: SessionDep,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
) -> DetailedChatbotResponse:
    """Remove a chatbot's custom avatar, falling back to the persona default."""
    try:
        chatbot_uuid = UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chatbot ID format")

    chatbot_repo = ChatbotRepository(session)
    chatbot = chatbot_repo.get(chatbot_uuid)
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")
    AccessService.verify_ownership(chatbot, user)

    previous_path = chatbot.avatar_storage_path
    updated_chatbot = chatbot_repo.update_chatbot(
        chatbot_id=chatbot_uuid,
        chatbot_in={"avatar_storage_path": None},
    )

    if previous_path:
        try:
            StorageManager().delete_file(previous_path)
        except Exception as e:
            logger.warning(f"Failed to delete avatar {previous_path}: {e}")

    return chatbot_service.build_detailed_response(updated_chatbot)


@router.get("/chatbots/{chatbot_id}/avatar")
def get_chatbot_avatar(
    chatbot_id: str,
    session: SessionDep,
    v: str | None = Query(default=None),
) -> StreamingResponse:
    """Stream a chatbot's custom avatar image through the API.

    ``v`` is ignored on the server. It's a cache-busting query param
    driven off the stored filename, so replacing the avatar forces a
    fresh fetch.
    """
    try:
        chatbot_uuid = UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    chatbot_repo = ChatbotRepository(session)
    chatbot = chatbot_repo.get(chatbot_uuid)
    if not chatbot or not chatbot.avatar_storage_path:
        raise HTTPException(status_code=404, detail="Avatar not found")

    storage_path = chatbot.avatar_storage_path
    mime_type, _ = mimetypes.guess_type(storage_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    storage = StorageManager()
    try:
        response = storage.client.get_object(
            bucket_name=storage.bucket_name,
            object_name=storage_path,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve avatar")

    # URL carries a hash of the stored filename, so any new upload
    # produces a new URL. safe to cache aggressively.
    return StreamingResponse(
        response.stream(),
        media_type=mime_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
