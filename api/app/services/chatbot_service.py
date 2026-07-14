"""High-level chatbot operations."""

import json
import logging
import re
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.core.config import settings
from app.core.storage import build_chatbot_avatar_url, build_chatbot_header_logo_url
from app.models.enums import ChatbotPersonaType, SourceType
from app.models.schemas import (
    ChatbotMoodleCourseInfo,
    ChatbotMoodleCoursesResponse,
    DetailedChatbotResponse,
    MoodleCourseActivityDetail,
    MoodleCourseFileDetail,
    MoodleCourseSectionDetail,
    MoodleCourseStructureResponse,
    MoodleGlossaryEntryDetail,
)
from app.models.tables import (
    Chatbot,
    DataSource,
    KnowledgeBaseDatasourceLink,
    MoodleCourse,
    MoodleDataSourceConfig,
    UploadedFile,
)
from app.repositories.chatbot import ChatbotRepository
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.services.persona_service import get_persona_for_chatbot
from app.services.selection_service import SelectionService

logger = logging.getLogger(__name__)


class ChatbotService:
    """High-level chatbot operations and response building."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.chatbot_repo = ChatbotRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)

    def get_chatbot(self, chatbot_id: UUID) -> Chatbot | None:
        return self.chatbot_repo.get(chatbot_id)

    def get_knowledge_base_links(
        self, knowledge_base_id: UUID
    ) -> list[KnowledgeBaseDatasourceLink]:
        return list(
            self.session.exec(
                select(KnowledgeBaseDatasourceLink).where(
                    KnowledgeBaseDatasourceLink.knowledge_base_id == knowledge_base_id
                )
            ).all()
        )

    def build_detailed_response(self, chatbot: Chatbot) -> DetailedChatbotResponse:
        """Build a DetailedChatbotResponse. Files and moodle courses come from their own endpoints."""
        kb = self.kb_repo.get(chatbot.knowledge_base_id)
        kb_status = kb.status if kb else "unknown"
        # surfaced inline on the edit page so the owner can self-diagnose a
        # failed sync (e.g. a Moodle token without download permission)
        last_sync_error = kb.last_sync_error if kb else None

        datasource_types = self._parse_datasource_types(chatbot.datasource_types)
        prompt_suggestions = self._parse_prompt_suggestions(chatbot.prompt_suggestions)

        avatar_url = build_chatbot_avatar_url(chatbot.id, chatbot.avatar_storage_path)
        header_logo_url = build_chatbot_header_logo_url(
            chatbot.id, chatbot.header_logo_storage_path
        )

        return DetailedChatbotResponse(
            id=chatbot.id,
            name=chatbot.name,
            description=chatbot.description,
            personaType=ChatbotPersonaType(chatbot.personaType),
            persona=get_persona_for_chatbot(chatbot),
            updated_at=chatbot.updated_at,
            enabled=chatbot.enabled,
            access_level=chatbot.access_level,
            api_enabled=chatbot.api_enabled,
            token=chatbot.token,
            status=kb_status,
            last_sync_error=last_sync_error,
            chatbot_url=f"{settings.FRONTEND_HOST}/chat/{chatbot.id}",
            cite_sources=chatbot.cite_sources,
            force_ocr=chatbot.force_ocr,
            persist_session=chatbot.persist_session,
            pii_filter_enabled=chatbot.pii_filter_enabled,
            chatbot_token="",
            prompt_suggestions=prompt_suggestions,
            datasource_types=datasource_types,
            avatar_storage_path=chatbot.avatar_storage_path,
            avatar_url=avatar_url,
            accent_color=chatbot.accent_color,
            header_logo_storage_path=chatbot.header_logo_storage_path,
            header_logo_url=header_logo_url,
            reindex_schedule_enabled=chatbot.reindex_schedule_enabled,
            reindex_schedule_frequency=chatbot.reindex_schedule_frequency,
            reindex_schedule_day_of_week=chatbot.reindex_schedule_day_of_week,
            reindex_schedule_day_of_month=chatbot.reindex_schedule_day_of_month,
            reindex_schedule_hour=chatbot.reindex_schedule_hour,
            reindex_schedule_minute=chatbot.reindex_schedule_minute,
            chat_request_count=chatbot.chat_request_count,
        )

    def build_moodle_courses_response(
        self,
        chatbot: Chatbot,
        moodle_datasource_ids: list[UUID],
        linked_course_ids: set[str],
    ) -> ChatbotMoodleCoursesResponse:
        """Public wrapper around _build_moodle_courses_response for route use."""
        return self._build_moodle_courses_response(
            chatbot, moodle_datasource_ids, linked_course_ids
        )

    def get_moodle_datasource_ids(
        self, kb_links: list[KnowledgeBaseDatasourceLink]
    ) -> list[UUID]:
        moodle_ids = []
        for link in kb_links:
            datasource = self.session.get(DataSource, link.datasource_id)
            if datasource and datasource.source_type == SourceType.MOODLE:
                moodle_ids.append(link.datasource_id)
        return moodle_ids

    def get_linked_course_ids(
        self, kb_links: list[KnowledgeBaseDatasourceLink]
    ) -> set[str]:
        linked_ids = set()
        for link in kb_links:
            datasource = self.session.get(DataSource, link.datasource_id)
            if datasource and datasource.source_type == SourceType.MOODLE:
                selections = SelectionService.parse_selections(link.selection)
                linked_ids.update(SelectionService.extract_course_ids(selections))
        return linked_ids

    def _parse_prompt_suggestions(self, raw: str | None) -> list[str] | None:
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def _parse_datasource_types(self, datasource_types: str | None) -> list[str]:
        if not datasource_types:
            return []
        return [t.strip() for t in datasource_types.split(",") if t.strip()]

    def _build_file_infos(self, selections: list[str]) -> list[dict[str, Any]]:
        files = []
        file_ids = SelectionService.extract_file_ids(selections)

        for file_id in file_ids:
            uploaded_file = self.session.get(UploadedFile, file_id)
            if uploaded_file:
                files.append(
                    {
                        "id": str(uploaded_file.id),
                        "filename": uploaded_file.original_filename,
                        "size": uploaded_file.file_size,
                        "mime_type": uploaded_file.mime_type,
                        "upload_date": uploaded_file.upload_date.isoformat(),
                        "status": uploaded_file.status.value
                        if hasattr(uploaded_file.status, "value")
                        else str(uploaded_file.status),
                    }
                )
        return files

    def _build_moodle_courses_response(
        self,
        chatbot: Chatbot,
        moodle_datasource_ids: list[UUID],
        linked_course_ids: set[str],
    ) -> ChatbotMoodleCoursesResponse:
        linked_courses = []
        available_courses = []

        for datasource_id in moodle_datasource_ids:
            datasource = self.session.get(DataSource, datasource_id)
            if not datasource or not datasource.moodle_config:
                continue

            moodle_config = datasource.moodle_config

            for course in moodle_config.moodle_courses:
                course_info = self._build_course_info(course, datasource, moodle_config)

                if course.moodle_course_id in linked_course_ids:
                    linked_courses.append(course_info)
                else:
                    available_courses.append(course_info)

        linked_courses.sort(key=lambda x: x.course_name)
        available_courses.sort(key=lambda x: x.course_name)

        return ChatbotMoodleCoursesResponse(
            chatbot_id=str(chatbot.id),
            chatbot_name=chatbot.name,
            knowledge_base_id=str(chatbot.knowledge_base_id),
            linked_moodle_datasources=[str(ds_id) for ds_id in moodle_datasource_ids],
            linked_courses=linked_courses,
            available_courses=available_courses,
            total_linked=len(linked_courses),
            total_available=len(available_courses),
            total_courses=len(linked_courses) + len(available_courses),
        )

    def _build_course_info(
        self,
        course: MoodleCourse,
        datasource: DataSource,
        moodle_config: MoodleDataSourceConfig,
    ) -> ChatbotMoodleCourseInfo:
        try:
            course_data = (
                json.loads(course.moodle_course_files)
                if course.moodle_course_files
                else {}
            )
            metadata = course_data.get("metadata", {})
        except json.JSONDecodeError:
            metadata = {}

        return ChatbotMoodleCourseInfo(
            course_id=course.moodle_course_id,
            course_name=course.moodle_course_name,
            shortname=None,
            description=metadata.get("description"),
            category=metadata.get("category"),
            course_url=None,
            datasource_id=str(datasource.id),
            datasource_name=datasource.name,
            moodle_domain=moodle_config.domain,
            total_sections=course.total_sections,
            total_activities=course.total_activities,
            selection_key=metadata.get(
                "selection_key", f"course:{course.moodle_course_id}"
            ),
            metadata_synced=course.metadata_last_sync is not None,
            last_metadata_sync=course.metadata_last_sync.isoformat()
            if course.metadata_last_sync
            else None,
            total_files=metadata.get("total_files", 0),
        )

    def course_belongs_to_chatbot(self, chatbot: Chatbot, course_id: str) -> bool:
        """True if the Moodle course is linked, without building the full structure."""
        kb_links = self.get_knowledge_base_links(chatbot.knowledge_base_id)
        for link in kb_links:
            datasource = self.session.get(DataSource, link.datasource_id)
            if not datasource or datasource.source_type != SourceType.MOODLE:
                continue
            if not datasource.moodle_config:
                continue
            for course in datasource.moodle_config.moodle_courses:
                if course.moodle_course_id == course_id:
                    return True
        return False

    def get_course_structure(
        self, chatbot: Chatbot, course_id: str
    ) -> MoodleCourseStructureResponse | None:
        """Hierarchical structure of a linked Moodle course."""
        kb_links = self.get_knowledge_base_links(chatbot.knowledge_base_id)

        for link in kb_links:
            datasource = self.session.get(DataSource, link.datasource_id)
            if not datasource or datasource.source_type != SourceType.MOODLE:
                continue
            if not datasource.moodle_config:
                continue

            for course in datasource.moodle_config.moodle_courses:
                if course.moodle_course_id != course_id:
                    continue

                course_data = {}
                if course.moodle_course_files:
                    try:
                        course_data = json.loads(course.moodle_course_files)
                    except json.JSONDecodeError:
                        pass

                structure = course_data.get("structure", {})
                sections = []

                for section_name, section_data in structure.items():
                    if section_name.startswith("_"):
                        continue
                    if not isinstance(section_data, dict):
                        continue

                    activities = []
                    for act_name, act_data in section_data.get(
                        "activities", {}
                    ).items():
                        files = [
                            MoodleCourseFileDetail(
                                id=f.get("id", ""),
                                filename=f.get("filename", ""),
                                filesize=f.get("filesize", 0),
                                mimetype=f.get("mimetype", ""),
                                selection_key=f.get("selection_key", ""),
                                download_url=f.get("download_url", ""),
                            )
                            for f in act_data.get("files", [])
                        ]
                        # glossary entries are indexed one document per entry
                        # and browsed individually, not via the activity itself
                        entries = [
                            MoodleGlossaryEntryDetail(
                                id=str(entry.get("id", "")),
                                concept=entry.get("concept", ""),
                            )
                            for entry in act_data.get("entries", [])
                        ]
                        # mirrors the worker's 50-char threshold for text content
                        desc = act_data.get("description", "")
                        plain = re.sub(r"<[^>]+>", "", desc).strip()
                        activities.append(
                            MoodleCourseActivityDetail(
                                id=act_data.get("id", ""),
                                name=act_name,
                                type=act_data.get("type", "unknown"),
                                description=desc,
                                files=files,
                                entries=entries,
                                has_indexed_content=len(plain) >= 50 or len(files) > 0,
                            )
                        )

                    summary = section_data.get("summary", "")
                    summary_plain = re.sub(r"<[^>]+>", "", summary).strip()
                    sections.append(
                        MoodleCourseSectionDetail(
                            id=str(section_data.get("id", "")),
                            name=section_name,
                            section_number=section_data.get("section_number", 0),
                            summary=summary,
                            activities=activities,
                            has_indexed_content=len(summary_plain) >= 50,
                        )
                    )

                sections.sort(key=lambda s: s.section_number)

                return MoodleCourseStructureResponse(
                    course_id=course.moodle_course_id,
                    course_name=course.moodle_course_name,
                    sections=sections,
                )

        return None
