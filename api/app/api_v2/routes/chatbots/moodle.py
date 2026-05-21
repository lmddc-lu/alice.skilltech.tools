"""Moodle-specific chatbot endpoints: course selection and content lookup."""

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Query
from sqlmodel import select

from app.api_v2.deps import ChatbotServiceDep, MoodleServiceDep, SessionDep, UserDep
from app.models.enums import SourceType
from app.models.schemas import (
    ChatbotMoodleCoursesResponse,
    MoodleCourseStructureResponse,
)
from app.models.tables import DataSource, KnowledgeBaseDatasourceLink
from app.repositories.chatbot import ChatbotRepository
from app.services.access_service import AccessService
from app.services.indexing_service import IndexingService
from app.services.rag_service import get_file_parsed_content
from app.services.selection_service import SelectionService

from .router import router
from .schemas import UpdateMoodleCoursesRequest

logger = logging.getLogger(__name__)


@router.get("/chatbots/{chatbot_id}/moodle-courses")
def get_chatbot_moodle_courses(
    chatbot_id: str,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
    moodle_service: MoodleServiceDep,
) -> ChatbotMoodleCoursesResponse:
    """Get Moodle courses linked to the chatbot, separated into linked and available."""
    try:
        chatbot_uuid = UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chatbot ID format")

    chatbot = chatbot_service.get_chatbot(chatbot_uuid)
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    kb_links = chatbot_service.get_knowledge_base_links(chatbot.knowledge_base_id)
    moodle_datasource_ids = chatbot_service.get_moodle_datasource_ids(kb_links)
    linked_course_ids = chatbot_service.get_linked_course_ids(kb_links)

    if not moodle_datasource_ids:
        return ChatbotMoodleCoursesResponse(
            chatbot_id=str(chatbot.id),
            chatbot_name=chatbot.name,
            knowledge_base_id=str(chatbot.knowledge_base_id),
            linked_moodle_datasources=[],
            linked_courses=[],
            available_courses=[],
            total_linked=0,
            total_available=0,
            total_courses=0,
            message="No Moodle datasources linked to this chatbot",
        )

    logger.info(f"Refreshing Moodle courses for chatbot {chatbot_id}")
    for datasource_id in moodle_datasource_ids:
        try:
            moodle_service.refresh_datasource_courses(
                chatbot_service.session, datasource_id
            )
        except Exception as e:
            logger.error(f"Failed to refresh datasource {datasource_id}: {e}")

    return chatbot_service.build_moodle_courses_response(
        chatbot, moodle_datasource_ids, linked_course_ids
    )


@router.patch("/chatbots/{chatbot_id}/moodle-courses")
async def update_chatbot_moodle_courses(
    chatbot_id: str,
    request: UpdateMoodleCoursesRequest,
    session: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    """Update Moodle courses for a chatbot's knowledge base."""
    chatbot_repo = ChatbotRepository(session)
    indexing_service = IndexingService(router.broker)

    try:
        chatbot_uuid = UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chatbot ID format")

    chatbot = chatbot_repo.get(chatbot_uuid)
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    kb_links = list(
        session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id
                == chatbot.knowledge_base_id
            )
        ).all()
    )

    if not kb_links:
        raise HTTPException(
            status_code=404, detail="No datasources found for this chatbot"
        )

    courses_added = []
    courses_removed = []
    moodle_datasource_found = False

    new_course_selections = set(
        SelectionService.build_course_selections(request.course_ids)
    )

    for link in kb_links:
        datasource = session.get(DataSource, link.datasource_id)
        if not datasource or datasource.source_type != SourceType.MOODLE:
            continue

        moodle_datasource_found = True

        selections = SelectionService.parse_selections(link.selection)
        current_course_selections = set(
            SelectionService.filter_course_selections(selections)
        )

        to_add = new_course_selections - current_course_selections
        to_remove = current_course_selections - new_course_selections

        courses_added = SelectionService.extract_course_ids(list(to_add))
        courses_removed = SelectionService.extract_course_ids(list(to_remove))

        if courses_added:
            logger.info(f"Adding courses to chatbot {chatbot_id}: {courses_added}")
        if courses_removed:
            logger.info(
                f"Removing courses from chatbot {chatbot_id}: {courses_removed}"
            )

        non_course_selections = SelectionService.filter_non_course_selections(
            selections
        )
        updated_selections = non_course_selections + list(new_course_selections)

        link.selection = SelectionService.serialize_selections(updated_selections)
        session.commit()

    if not moodle_datasource_found:
        raise HTTPException(
            status_code=404, detail="No Moodle datasources found for this chatbot"
        )

    response = {
        "message": "Moodle course selection updated successfully",
        "chatbot_id": str(chatbot.id),
        "courses_added": courses_added,
        "courses_removed": courses_removed,
        "total_added": len(courses_added),
        "total_removed": len(courses_removed),
        "current_courses": request.course_ids,
        "total_courses": len(request.course_ids),
        "reindexing": False,
    }

    if courses_added or courses_removed:
        success, error = await indexing_service.trigger_reindex_safe(
            session=session,
            knowledge_base_id=chatbot.knowledge_base_id,
            user=user,
            force=True,
        )
        response["reindexing"] = success
        if success:
            response["message"] = (
                "Moodle course selection updated and re-indexing started"
            )
        if error:
            response["reindex_error"] = error

    return response


@router.get("/chatbots/{chatbot_id}/moodle-courses/{course_id}/structure")
def get_moodle_course_structure(
    chatbot_id: str,
    course_id: str,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
) -> MoodleCourseStructureResponse:
    """Get the hierarchical structure of a Moodle course (sections, activities, files)."""
    try:
        chatbot_uuid = UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chatbot ID format")

    chatbot = chatbot_service.get_chatbot(chatbot_uuid)
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    result = chatbot_service.get_course_structure(chatbot, course_id)
    if not result:
        raise HTTPException(status_code=404, detail="Course not found in this chatbot")

    return result


@router.get("/chatbots/{chatbot_id}/moodle-content/{course_id}/parsed")
async def get_moodle_parsed_content(
    chatbot_id: str,
    course_id: str,
    user: UserDep,
    chatbot_service: ChatbotServiceDep,
    activity_id: str | None = Query(default=None),
    file_id: str | None = Query(default=None),
    section_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return parsed text of a Moodle activity or file from the vector store.

    Constructs the deterministic file_id used during indexing:
    - activity text: moodle_activity_{course_id}_{activity_id}
    - attached file: moodle_file_{course_id}_{activity_id}_{file_id}
    - section text: moodle_section_{course_id}_{section_id}
    """
    try:
        chatbot_uuid = UUID(chatbot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chatbot ID format")

    chatbot = chatbot_service.get_chatbot(chatbot_uuid)
    if not chatbot:
        raise HTTPException(status_code=404, detail="Chatbot not found")

    AccessService.verify_ownership(chatbot, user)

    if not chatbot_service.course_belongs_to_chatbot(chatbot, course_id):
        raise HTTPException(status_code=404, detail="Course not found in this chatbot")

    # must match the file_id the worker assigns during indexing
    lookup_file_id = None
    if file_id and activity_id:
        lookup_file_id = f"moodle_file_{course_id}_{activity_id}_{file_id}"
    elif activity_id:
        lookup_file_id = f"moodle_activity_{course_id}_{activity_id}"
    elif section_id:
        lookup_file_id = f"moodle_section_{course_id}_{section_id}"
    else:
        raise HTTPException(
            status_code=400,
            detail="One of activity_id, file_id+activity_id, or section_id is required",
        )

    index_name = str(chatbot.knowledge_base_id)

    logger.debug(
        "Moodle parsed content lookup: index=%s, file_id=%s",
        index_name,
        lookup_file_id,
    )

    result = await get_file_parsed_content(
        index_name=index_name,
        file_name="",
        file_id=lookup_file_id,
    )

    return result
