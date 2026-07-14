"""Chatbot creation endpoints from local files or from a Moodle instance."""

import json
import logging

from fastapi import File, Form, HTTPException, Request, UploadFile

from app.api_v2.deps import (
    DatasourceServiceDep,
    FileServiceDep,
    SessionDep,
    UserDep,
)
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.enums import (
    ChatbotPersonaType,
    KnowledgeBaseStatus,
    SourceType,
    SyncErrorCode,
)
from app.models.schemas import (
    DataSourceCreate,
    DetailedChatbotResponse,
    MoodleConfigCreate,
)
from app.models.tables import ChatbotBase
from app.repositories.chatbot import ChatbotRepository
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.services.indexing_service import IndexingService
from app.services.selection_service import SelectionService

from .router import router

logger = logging.getLogger(__name__)


@router.post("/chatbots/create-from-files")
@limiter.limit("10/minute")
async def create_chatbot_from_files(
    request: Request,
    name: str = Form(...),
    description: str | None = Form(None),
    persona: str | None = Form(None),
    persona_type: ChatbotPersonaType = Form(default=ChatbotPersonaType.TEACHER),
    prompt_suggestions: str | None = Form(None),
    cite_sources: bool = Form(default=True),
    force_ocr: bool = Form(default=False),
    files: list[UploadFile] = File(default=[]),
    text_entries: str = Form(default="[]"),
    session: SessionDep = None,  # type: ignore[assignment]
    user: UserDep = None,  # type: ignore[assignment]
    file_service: FileServiceDep = None,  # type: ignore[assignment]
    datasource_service: DatasourceServiceDep = None,  # type: ignore[assignment]
) -> DetailedChatbotResponse:
    """Create a chatbot from uploaded files in a single step.

    ``text_entries`` is a JSON array of ``{title, content}`` objects for
    free-text entries the user typed in the wizard.
    """
    try:
        parsed_text_entries = json.loads(text_entries) if text_entries else []
        if not isinstance(parsed_text_entries, list):
            raise ValueError("text_entries must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid text_entries format: {str(e)}"
        )

    if (not files or len(files) == 0) and not parsed_text_entries:
        raise HTTPException(
            status_code=400,
            detail="At least one file or text entry must be provided",
        )

    chatbot_repo = ChatbotRepository(session)
    kb_repo = KnowledgeBaseRepository(session)
    indexing_service = IndexingService(router.broker)

    try:
        datasource_create = DataSourceCreate(
            name=f"Files for: {name}",
            source_type=SourceType.FILE,
            moodle_config=None,
            nextcloud_config=None,
        )
        datasource = await datasource_service.create_datasource(datasource_create, user)
        logger.info(f"Created FILE datasource {datasource.id} for chatbot '{name}'")

        uploaded_files = []
        if files:
            uploaded_files = await file_service.upload_files(
                session=session,
                user=user,
                datasource_id=datasource.id,
                files=files,
            )

        for entry in parsed_text_entries:
            title = (entry or {}).get("title", "")
            content = (entry or {}).get("content", "")
            if not content or not str(content).strip():
                continue
            try:
                uploaded_text = await file_service.upload_text_entry(
                    session=session,
                    user=user,
                    datasource_id=datasource.id,
                    title=str(title),
                    content=str(content),
                )
                uploaded_files.append(uploaded_text)
            except Exception as e:
                logger.error(f"Failed to upload text entry '{title}': {e}")

        if not uploaded_files:
            raise HTTPException(
                status_code=500,
                detail="Failed to upload any files. Please check file formats and sizes.",
            )

        knowledge_base = kb_repo.create_knowledge_base(
            name=f"KB: {name}",
            description=f"Automatically created for chatbot: {name}",
            user_id=user.id,
        )
        logger.info(f"Created knowledge base {knowledge_base.id} for chatbot '{name}'")

        file_selections = SelectionService.build_file_selections(
            [uf.id for uf in uploaded_files]
        )
        kb_repo.add_datasource(
            knowledge_base_id=knowledge_base.id,
            datasource_id=datasource.id,
            selection=file_selections,
        )
        logger.info(f"Linked {len(file_selections)} files to knowledge base")

        chatbot_data = ChatbotBase(
            name=name,
            description=description,
            persona=persona,
            personaType=persona_type,
            prompt_suggestions=prompt_suggestions,
            cite_sources=cite_sources,
            force_ocr=force_ocr,
            knowledge_base_id=knowledge_base.id,
            datasource_types="FILE",
        )
        chatbot = chatbot_repo.create_chatbot(chatbot=chatbot_data, owner_id=user.id)
        logger.info(f"Created chatbot {chatbot.id} with name '{name}'")

        # keep the chatbot row even if publish fails. trigger_reindex's
        # exception path marks the KB ERROR so the user can retry from the
        # Synchronize button. surface the error so the UI doesn't pretend
        # the sync started.
        reindex_ok, _ = await indexing_service.trigger_reindex_safe(
            session=session,
            knowledge_base_id=knowledge_base.id,
            user=user,
            force_ocr=force_ocr,
        )

        return DetailedChatbotResponse(
            id=chatbot.id,
            name=chatbot.name,
            description=chatbot.description,
            personaType=ChatbotPersonaType(chatbot.personaType),
            persona=chatbot.persona,
            knowledge_base_id=chatbot.knowledge_base_id,
            owner_id=chatbot.owner_id,
            owner_email=chatbot.owner.email,
            created_at=chatbot.created_at,
            updated_at=chatbot.updated_at,
            enabled=chatbot.enabled,
            access_level=chatbot.access_level,
            api_enabled=chatbot.api_enabled,
            token=chatbot.token,
            status=(
                KnowledgeBaseStatus.PROCESSING
                if reindex_ok
                else KnowledgeBaseStatus.ERROR
            ),
            last_sync_error=None if reindex_ok else SyncErrorCode.FAILED,
            course_count=len(uploaded_files),
            chatbot_token="",
            chatbot_url=f"{settings.FRONTEND_HOST}/chat/{chatbot.id}",
            datasource_types=["FILE"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating chatbot from files: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create chatbot: {str(e)}"
        )


@router.post("/chatbots/create-from-moodle")
async def create_chatbot_from_moodle(
    name: str = Form(...),
    description: str | None = Form(None),
    persona: str | None = Form(None),
    persona_type: ChatbotPersonaType = Form(default=ChatbotPersonaType.TEACHER),
    prompt_suggestions: str | None = Form(None),
    cite_sources: bool = Form(default=True),
    moodle_url: str = Form(...),
    moodle_token: str = Form(...),
    course_ids: str = Form(...),
    force_ocr: bool = Form(default=False),
    files: list[UploadFile] = File(default=[]),
    text_entries: str = Form(default="[]"),
    session: SessionDep = None,  # type: ignore[assignment]
    user: UserDep = None,  # type: ignore[assignment]
    file_service: FileServiceDep = None,  # type: ignore[assignment]
    datasource_service: DatasourceServiceDep = None,  # type: ignore[assignment]
) -> DetailedChatbotResponse:
    """Create a chatbot from Moodle courses and optionally additional files.

    ``text_entries`` is an optional JSON array of ``{title, content}``
    objects persisted as free-text files alongside any uploads.
    """
    try:
        parsed_text_entries = json.loads(text_entries) if text_entries else []
        if not isinstance(parsed_text_entries, list):
            raise ValueError("text_entries must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid text_entries format: {str(e)}"
        )
    chatbot_repo = ChatbotRepository(session)
    kb_repo = KnowledgeBaseRepository(session)
    indexing_service = IndexingService(router.broker)

    try:
        parsed_course_ids = json.loads(course_ids)
        if not isinstance(parsed_course_ids, list) or len(parsed_course_ids) == 0:
            raise ValueError("course_ids must be a non-empty array")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid course_ids format. Must be a JSON array: {str(e)}",
        )

    try:
        moodle_datasource_create = DataSourceCreate(
            name=f"Moodle courses for: {name}",
            source_type=SourceType.MOODLE,
            moodle_config=MoodleConfigCreate(
                domain=moodle_url.rstrip("/"), token=moodle_token
            ),
        )
        moodle_datasource = await datasource_service.create_datasource(
            moodle_datasource_create, user
        )
        logger.info(f"Created MOODLE datasource {moodle_datasource.id}")

        try:
            metadata_sync_job = datasource_service.prepare_metadata_sync_job(
                moodle_datasource.id, user, force=False
            )
            await router.broker.publish(
                json.dumps(metadata_sync_job), routing_key="metadata_sync_jobs"
            )
        except Exception as e:
            logger.warning(f"Failed to trigger metadata sync: {str(e)}")

        file_datasource = None
        uploaded_files = []
        has_file_content = (files and len(files) > 0) or bool(parsed_text_entries)
        if has_file_content:
            file_datasource_create = DataSourceCreate(
                name=f"Additional files for: {name}",
                source_type=SourceType.FILE,
                moodle_config=None,
                nextcloud_config=None,
            )
            file_datasource = await datasource_service.create_datasource(
                file_datasource_create, user
            )

            if files and len(files) > 0:
                uploaded_files = await file_service.upload_files(
                    session=session,
                    user=user,
                    datasource_id=file_datasource.id,
                    files=files,
                )

            for entry in parsed_text_entries:
                title = (entry or {}).get("title", "")
                content = (entry or {}).get("content", "")
                if not content or not str(content).strip():
                    continue
                try:
                    uploaded_text = await file_service.upload_text_entry(
                        session=session,
                        user=user,
                        datasource_id=file_datasource.id,
                        title=str(title),
                        content=str(content),
                    )
                    uploaded_files.append(uploaded_text)
                except Exception as e:
                    logger.error(f"Failed to upload text entry '{title}': {e}")

        knowledge_base = kb_repo.create_knowledge_base(
            name=f"KB: {name}",
            description=f"Automatically created for chatbot: {name}",
            user_id=user.id,
        )
        logger.info(f"Created knowledge base {knowledge_base.id}")

        total_selections = 0

        course_selections = SelectionService.build_course_selections(parsed_course_ids)
        kb_repo.add_datasource(
            knowledge_base_id=knowledge_base.id,
            datasource_id=moodle_datasource.id,
            selection=course_selections,
        )
        total_selections += len(course_selections)

        if file_datasource and uploaded_files:
            file_selections = SelectionService.build_file_selections(
                [uf.id for uf in uploaded_files]
            )
            kb_repo.add_datasource(
                knowledge_base_id=knowledge_base.id,
                datasource_id=file_datasource.id,
                selection=file_selections,
            )
            total_selections += len(file_selections)

        chatbot_data = ChatbotBase(
            name=name,
            description=description,
            persona=persona,
            personaType=persona_type,
            prompt_suggestions=prompt_suggestions,
            cite_sources=cite_sources,
            force_ocr=force_ocr,
            knowledge_base_id=knowledge_base.id,
            datasource_types="MOODLE,FILE",
        )
        chatbot = chatbot_repo.create_chatbot(chatbot=chatbot_data, owner_id=user.id)
        logger.info(f"Created chatbot {chatbot.id} with name '{name}'")

        # see create_chatbot_from_files for why a publish failure does not
        # roll back the chatbot
        reindex_ok, _ = await indexing_service.trigger_reindex_safe(
            session=session,
            knowledge_base_id=knowledge_base.id,
            user=user,
            force_ocr=force_ocr,
        )

        return DetailedChatbotResponse(
            id=chatbot.id,
            name=chatbot.name,
            description=chatbot.description,
            personaType=ChatbotPersonaType(chatbot.personaType),
            persona=chatbot.persona,
            knowledge_base_id=chatbot.knowledge_base_id,
            owner_id=chatbot.owner_id,
            owner_email=chatbot.owner.email,
            created_at=chatbot.created_at,
            updated_at=chatbot.updated_at,
            enabled=chatbot.enabled,
            access_level=chatbot.access_level,
            api_enabled=chatbot.api_enabled,
            token=chatbot.token,
            status=(
                KnowledgeBaseStatus.PROCESSING
                if reindex_ok
                else KnowledgeBaseStatus.ERROR
            ),
            last_sync_error=None if reindex_ok else SyncErrorCode.FAILED,
            course_count=total_selections,
            chatbot_token="",
            chatbot_url=f"{settings.FRONTEND_HOST}/chat/{chatbot.id}",
            datasource_types=["MOODLE", "FILE"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating chatbot from Moodle: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create chatbot: {str(e)}"
        )
