"""File-management endpoints for a chatbot's knowledge base.

- ``PATCH /chatbots/{id}/files``: add, remove, or replace files and text entries
- ``GET   /chatbots/{id}/files``: owner listing with ingestion state
- ``GET   /chatbots/{id}/files/{file_id}/text``: raw content of a free-text entry
- ``GET   /chatbots/{id}/files/{file_id}/download``: stream a file (owner)
- ``GET   /chatbots/{id}/files/{file_id}/parsed-content``: extracted text from the vector store
- ``GET   /chatbots/{id}/files/{file_id}/preview``: stream a file to end-users (access-gated)
"""

import json
import logging
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

from fastapi import File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import select

from app.api_v2.deps import (
    ChatbotServiceDep,
    DatasourceServiceDep,
    FileServiceDep,
    OptionalUserDep,
    SessionDep,
    UserDep,
)
from app.core.rate_limit import limiter
from app.core.storage import StorageManager
from app.models.enums import SourceType
from app.models.schemas import DataSourceCreate
from app.models.tables import DataSource, KnowledgeBaseDatasourceLink, UploadedFile
from app.repositories.chatbot import ChatbotRepository
from app.repositories.job import JobRepository
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.services.access_service import AccessService
from app.services.indexing_service import IndexingService
from app.services.rag_service import get_file_parsed_content
from app.services.selection_service import SelectionService

from .router import router
from .schemas import TextEntryContentResponse

logger = logging.getLogger(__name__)


@router.patch("/chatbots/{chatbot_id}/files")
@limiter.limit("20/minute")
async def update_chatbot_files(
    request: Request,
    chatbot_id: str,
    files: list[UploadFile] = File(default=[]),
    file_ids_to_delete: str = Form(default="[]"),
    text_entries: str = Form(default="[]"),
    session: SessionDep = None,  # type: ignore[assignment]
    user: UserDep = None,  # type: ignore[assignment]
    file_service: FileServiceDep = None,  # type: ignore[assignment]
    datasource_service: DatasourceServiceDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Update chatbot files by adding, deleting, or replacing free-text entries.

    ``text_entries`` is a JSON array of
    ``{title, content, file_id_to_replace?}``. Each entry is persisted as
    a ``text/plain`` upload, and any ``file_id_to_replace`` is removed
    in the same call.
    """
    chatbot_repo = ChatbotRepository(session)
    kb_repo = KnowledgeBaseRepository(session)
    indexing_service = IndexingService(router.broker)

    try:
        chatbot_uuid = UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chatbot ID format")

    chatbot = chatbot_repo.get(chatbot_uuid)
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    try:
        file_ids_list = json.loads(file_ids_to_delete)
        if not isinstance(file_ids_list, list):
            raise ValueError("file_ids_to_delete must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file_ids_to_delete format: {str(e)}",
        )

    try:
        text_entries_list = json.loads(text_entries) if text_entries else []
        if not isinstance(text_entries_list, list):
            raise ValueError("text_entries must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid text_entries format: {str(e)}",
        )

    # fold replacement targets into the delete path so they share one
    # commit and one reindex
    replace_ids: list[str] = []
    for entry in text_entries_list:
        replace_id = (entry or {}).get("file_id_to_replace")
        if replace_id:
            replace_ids.append(str(replace_id))
    combined_delete_ids = list({*(str(fid) for fid in file_ids_list), *replace_ids})

    if not files and not combined_delete_ids and not text_entries_list:
        raise HTTPException(
            status_code=400,
            detail="At least one file or text entry to add or delete must be provided",
        )

    uploaded_files_response = []
    deleted_file_ids = []

    kb_links = list(
        session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id
                == chatbot.knowledge_base_id
            )
        ).all()
    )

    if combined_delete_ids:
        if not kb_links:
            raise HTTPException(
                status_code=404, detail="No datasources found for this chatbot"
            )
        deleted_file_ids = file_service.delete_files_from_selections(
            session, kb_links, combined_delete_ids
        )

    has_adds = (files and len(files) > 0) or bool(text_entries_list)
    if has_adds:
        # refresh KB links after deletion
        kb_links = list(
            session.exec(
                select(KnowledgeBaseDatasourceLink).where(
                    KnowledgeBaseDatasourceLink.knowledge_base_id
                    == chatbot.knowledge_base_id
                )
            ).all()
        )

        file_datasource_id, file_datasource_link = (
            file_service.get_file_datasource_link(session, kb_links)
        )

        if file_datasource_id is None:
            logger.info(f"Creating FILE datasource for chatbot {chatbot_id}")
            file_datasource_create = DataSourceCreate(
                name=f"Additional files for: {chatbot.name}",
                source_type=SourceType.FILE,
                moodle_config=None,
                nextcloud_config=None,
            )
            file_datasource = await datasource_service.create_datasource(
                file_datasource_create, user
            )
            file_datasource_id = file_datasource.id
            file_datasource_link = kb_repo.add_datasource(
                knowledge_base_id=chatbot.knowledge_base_id,
                datasource_id=file_datasource_id,
                selection=[],
            )

        if files and len(files) > 0:
            uploaded_files_response = await file_service.upload_files(
                session=session,
                user=user,
                datasource_id=file_datasource_id,
                files=files,
            )

        for entry in text_entries_list:
            title = (entry or {}).get("title", "")
            content = (entry or {}).get("content", "")
            if not content or not str(content).strip():
                continue
            try:
                uploaded_text = await file_service.upload_text_entry(
                    session=session,
                    user=user,
                    datasource_id=file_datasource_id,
                    title=str(title),
                    content=str(content),
                )
                uploaded_files_response.append(uploaded_text)
            except Exception as e:
                logger.error(f"Failed to upload text entry '{title}': {e}")

        if uploaded_files_response and file_datasource_link is not None:
            file_service.add_files_to_selection(
                session,
                file_datasource_link,
                cast(Any, uploaded_files_response),
            )

    reindexing_started = False
    reindex_error = None

    if deleted_file_ids or uploaded_files_response:
        # incremental: only added files are ingested; deleted files are
        # removed from the index by the worker's orphan cleanup
        reindexing_started, reindex_error = await indexing_service.trigger_reindex_safe(
            session=session,
            knowledge_base_id=chatbot.knowledge_base_id,
            user=user,
            force=False,
        )

    return {
        "message": "Files updated successfully",
        "chatbot_id": str(chatbot.id),
        "files_added": [
            {
                "id": str(uf.id),
                "filename": uf.original_filename,
                "size": uf.file_size,
                "mime_type": uf.mime_type,
            }
            for uf in uploaded_files_response
        ],
        "files_deleted": deleted_file_ids,
        "total_added": len(uploaded_files_response),
        "total_deleted": len(deleted_file_ids),
        "reindexing": reindexing_started,
        "reindex_error": reindex_error,
    }


@router.get("/chatbots/{chatbot_id}/files/{file_id}/text")
def get_chatbot_text_entry(
    chatbot_id: str,
    file_id: str,
    session: SessionDep,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
) -> TextEntryContentResponse:
    """Return the raw content of a free-text entry for editing."""
    chatbot = chatbot_service.get_chatbot(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")
    AccessService.verify_ownership(chatbot, user)

    kb_links = chatbot_service.get_knowledge_base_links(chatbot.knowledge_base_id)
    file_belongs = False
    for link in kb_links:
        datasource = session.get(DataSource, link.datasource_id)
        if not datasource or datasource.source_type != SourceType.FILE:
            continue
        selections = SelectionService.parse_selections(link.selection)
        if UUID(file_id) in SelectionService.extract_file_ids(selections):
            file_belongs = True
            break
    if not file_belongs:
        raise HTTPException(status_code=404, detail="File not found in this chatbot")

    uploaded_file = session.get(UploadedFile, UUID(file_id))
    if not uploaded_file:
        raise HTTPException(status_code=404, detail="File not found")
    if not getattr(uploaded_file, "is_free_text", False):
        raise HTTPException(status_code=400, detail="File is not a text entry")

    storage = StorageManager()
    try:
        response = storage.client.get_object(
            bucket_name=storage.bucket_name,
            object_name=uploaded_file.storage_path,
        )
        content = response.read().decode("utf-8")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load text content")

    # strip .txt so the user sees the title they originally entered
    title = uploaded_file.original_filename
    if title.lower().endswith(".txt"):
        title = title[:-4]

    return TextEntryContentResponse(
        id=uploaded_file.id,
        title=title,
        content=content,
    )


@router.get("/chatbots/{chatbot_id}/files")
def get_chatbot_files(
    chatbot_id: str,
    session: SessionDep,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
) -> dict[str, Any]:
    """Get the list of files associated with a chatbot.

    Each file is enriched with ``ingestion_state`` and ``ingestion_error``
    from the latest job's ``JobFile`` row, so the frontend doesn't have
    to stitch a separate ``/job-status`` call to show ingestion failures.
    """
    chatbot = chatbot_service.get_chatbot(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    kb_links = chatbot_service.get_knowledge_base_links(chatbot.knowledge_base_id)

    if not kb_links:
        return {
            "chatbot_id": str(chatbot.id),
            "files": [],
            "total_files": 0,
            "failed_ingestion_count": 0,
        }

    job_repo = JobRepository(session)
    latest_job = job_repo.get_latest_for_knowledge_base(chatbot.knowledge_base_id)
    job_file_by_id: dict[str, tuple[str, str | None, str | None]] = {}
    if latest_job is not None:
        for jf in job_repo.get_job_files(latest_job.id):
            job_file_by_id[jf.external_file_id] = (
                jf.state,
                jf.error_message,
                jf.error_code,
            )

    all_files = []
    failed_count = 0
    for link in kb_links:
        datasource = session.get(DataSource, link.datasource_id)
        if not datasource or datasource.source_type != SourceType.FILE:
            continue

        selections = SelectionService.parse_selections(link.selection)
        file_ids = SelectionService.extract_file_ids(selections)

        for file_id in file_ids:
            uploaded_file = session.get(UploadedFile, file_id)
            if not uploaded_file:
                continue
            state, error_message, error_code = job_file_by_id.get(
                str(uploaded_file.id), (None, None, None)
            )
            if state == "failed":
                failed_count += 1
            all_files.append(
                {
                    "id": str(uploaded_file.id),
                    "filename": uploaded_file.original_filename,
                    "size": uploaded_file.file_size,
                    "mime_type": uploaded_file.mime_type,
                    "upload_date": uploaded_file.upload_date.isoformat(),
                    "status": uploaded_file.status,
                    "is_free_text": bool(getattr(uploaded_file, "is_free_text", False)),
                    "ingestion_state": state,
                    "ingestion_error": error_message,
                    "ingestion_error_code": error_code,
                }
            )

    return {
        "chatbot_id": str(chatbot.id),
        "files": all_files,
        "total_files": len(all_files),
        "failed_ingestion_count": failed_count,
    }


@router.get("/chatbots/{chatbot_id}/files/{file_id}/download")
def download_file(
    chatbot_id: str,
    file_id: str,
    session: SessionDep,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
) -> StreamingResponse:
    """Stream a chatbot file to the browser for preview or download."""

    chatbot = chatbot_service.get_chatbot(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    kb_links = chatbot_service.get_knowledge_base_links(chatbot.knowledge_base_id)
    file_belongs_to_chatbot = False
    for link in kb_links:
        datasource = session.get(DataSource, link.datasource_id)
        if not datasource or datasource.source_type != SourceType.FILE:
            continue
        selections = SelectionService.parse_selections(link.selection)
        file_ids = SelectionService.extract_file_ids(selections)
        if UUID(file_id) in file_ids:
            file_belongs_to_chatbot = True
            break

    if not file_belongs_to_chatbot:
        raise HTTPException(status_code=404, detail="File not found in this chatbot")

    uploaded_file = session.get(UploadedFile, UUID(file_id))
    if not uploaded_file:
        raise HTTPException(status_code=404, detail="File not found")

    storage = StorageManager()
    try:
        response = storage.client.get_object(
            bucket_name=storage.bucket_name,
            object_name=uploaded_file.storage_path,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve file")

    inline_types = {"application/pdf", "text/plain", "text/html", "text/csv"}
    disposition_type = (
        "inline" if uploaded_file.mime_type in inline_types else "attachment"
    )

    # RFC 5987: ASCII fallback plus UTF-8 filename* for non-ASCII names
    ascii_filename = uploaded_file.original_filename.encode("ascii", "replace").decode()
    utf8_filename = quote(uploaded_file.original_filename)
    disposition = (
        f'{disposition_type}; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{utf8_filename}"
    )

    return StreamingResponse(
        response.stream(),
        media_type=uploaded_file.mime_type,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(uploaded_file.file_size),
        },
    )


@router.get("/chatbots/{chatbot_id}/files/{file_id}/parsed-content")
async def get_file_parsed_content_endpoint(
    chatbot_id: str,
    file_id: str,
    session: SessionDep,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
) -> dict[str, Any]:
    """Return the full extracted/parsed text of a file from its vector store chunks."""
    chatbot = chatbot_service.get_chatbot(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    kb_links = chatbot_service.get_knowledge_base_links(chatbot.knowledge_base_id)
    file_belongs_to_chatbot = False
    for link in kb_links:
        datasource = session.get(DataSource, link.datasource_id)
        if not datasource or datasource.source_type != SourceType.FILE:
            continue
        selections = SelectionService.parse_selections(link.selection)
        file_ids = SelectionService.extract_file_ids(selections)
        if UUID(file_id) in file_ids:
            file_belongs_to_chatbot = True
            break

    if not file_belongs_to_chatbot:
        raise HTTPException(status_code=404, detail="File not found in this chatbot")

    uploaded_file = session.get(UploadedFile, UUID(file_id))
    if not uploaded_file:
        raise HTTPException(status_code=404, detail="File not found")

    result = await get_file_parsed_content(
        index_name=str(chatbot.knowledge_base_id),
        file_name=uploaded_file.original_filename,
        stored_filename=uploaded_file.stored_filename,
        file_id=str(uploaded_file.id),
    )

    return result


@router.get("/chatbots/{chatbot_id}/files/{file_id}/preview")
def preview_file(
    chatbot_id: str,
    file_id: str,
    session: SessionDep,
    user: OptionalUserDep,
    chatbot_service: ChatbotServiceDep,
    password: str | None = Query(default=None),
) -> StreamingResponse:
    """Preview/download a chatbot file with the same access rules as chat."""
    chatbot = chatbot_service.get_chatbot(UUID(chatbot_id))
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_access(chatbot, user, password)

    kb_links = chatbot_service.get_knowledge_base_links(chatbot.knowledge_base_id)
    file_belongs_to_chatbot = False
    for link in kb_links:
        datasource = session.get(DataSource, link.datasource_id)
        if not datasource or datasource.source_type != SourceType.FILE:
            continue
        selections = SelectionService.parse_selections(link.selection)
        file_ids = SelectionService.extract_file_ids(selections)
        if UUID(file_id) in file_ids:
            file_belongs_to_chatbot = True
            break

    if not file_belongs_to_chatbot:
        raise HTTPException(status_code=404, detail="File not found in this chatbot")

    uploaded_file = session.get(UploadedFile, UUID(file_id))
    if not uploaded_file:
        raise HTTPException(status_code=404, detail="File not found")

    storage = StorageManager()
    try:
        response = storage.client.get_object(
            bucket_name=storage.bucket_name,
            object_name=uploaded_file.storage_path,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve file")

    inline_types = {"application/pdf", "text/plain", "text/html", "text/csv"}
    disposition_type = (
        "inline" if uploaded_file.mime_type in inline_types else "attachment"
    )

    ascii_filename = uploaded_file.original_filename.encode("ascii", "replace").decode()
    utf8_filename = quote(uploaded_file.original_filename)
    disposition = (
        f'{disposition_type}; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{utf8_filename}"
    )

    return StreamingResponse(
        response.stream(),
        media_type=uploaded_file.mime_type,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(uploaded_file.file_size),
        },
    )
