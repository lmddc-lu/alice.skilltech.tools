import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ChatbotPersonaType,
    DataSourceSyncStatus,
    FileStatus,
    KnowledgeBaseStatus,
    SourceType,
)
from app.models.tables import (
    ChatbotBase,
    MoodleCourseChatbotMappingBase,
    MoodleIntegrationBase,
)


class KnowledgeBaseResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    last_sync: datetime | None = None
    last_sync_error: str | None = None
    description: str | None = None
    user_id: uuid.UUID
    user_email: str
    datasources: list[str] = []


class MessageQuery(BaseModel):
    query: str
    source_doc_token: str


class StatelessChatRequest(BaseModel):
    messages: list[dict[str, str]]
    source_doc_token: str | None = None
    course_id: int


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    error: bool = False
    tokens_used: int | None = None
    processing_time: float | None = None
    model_config = ConfigDict(from_attributes=True)


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    title: str | None = None
    created_at: datetime
    last_message_at: datetime
    chatbot_id: uuid.UUID
    messages: list[ChatMessageResponse]


class UploadedFileResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    file_size: int
    mime_type: str
    tags: list[str]
    status: FileStatus
    upload_date: datetime
    processed_date: datetime | None = None
    extracted_text_length: int
    processing_error: str | None = None
    selection_key: str
    storage_path: str
    is_free_text: bool = False
    model_config = ConfigDict(from_attributes=True)


class FileUploadRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    overwrite: bool = Field(default=False, description="Overwrite if file exists")


class FileUploadBatchRequest(BaseModel):
    file_ids: list[uuid.UUID]
    operation: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class FileSearchRequest(BaseModel):
    filename_pattern: str | None = None
    tags: list[str] = Field(default_factory=list)
    mime_types: list[str] = Field(default_factory=list)
    status: FileStatus | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    min_size: int | None = None
    max_size: int | None = None


class MoodleIntegrationResponse(MoodleIntegrationBase):
    id: uuid.UUID
    token: str
    created_at: datetime
    updated_at: datetime
    default_chatbot: ChatbotBase | None = None
    course_mappings_count: int = 0
    model_config = ConfigDict(from_attributes=True)  # type: ignore[assignment]


class MoodleCourseMappingResponse(MoodleCourseChatbotMappingBase):
    id: uuid.UUID
    moodle_integration_id: uuid.UUID
    created_at: datetime
    chatbot_name: str | None = None
    chatbot_description: str | None = None
    model_config = ConfigDict(from_attributes=True)  # type: ignore[assignment]


class ChatbotResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    persona: str | None = None
    personaType: ChatbotPersonaType = ChatbotPersonaType.TEACHER
    knowledge_base_id: uuid.UUID
    owner_id: uuid.UUID
    owner_email: str | None = None
    created_at: datetime
    updated_at: datetime
    enabled: bool
    access_level: str
    api_enabled: bool = False
    token: str | None = None
    cite_sources: bool = True
    pii_filter_enabled: bool = False
    status: str = KnowledgeBaseStatus.READY
    model_config = ConfigDict(from_attributes=True)


class PublicChatbotResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    status: str
    enabled: bool
    access_level: str
    personaType: ChatbotPersonaType
    prompt_suggestions: list[str] | None = None
    avatar_url: str | None = None
    persist_session: bool = False
    accent_color: str | None = None
    header_logo_url: str | None = None
    model_config = ConfigDict(from_attributes=True)


class ChatbotFileInfo(BaseModel):
    id: str
    filename: str
    size: int
    mime_type: str
    upload_date: str
    status: str
    model_config = ConfigDict(from_attributes=True)


class DetailedChatbotResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    persona: str | None = None
    personaType: ChatbotPersonaType
    updated_at: datetime
    enabled: bool
    access_level: str
    api_enabled: bool = False
    token: str | None = None
    cite_sources: bool = True
    force_ocr: bool = False
    persist_session: bool = False
    pii_filter_enabled: bool = False
    status: str
    last_sync_error: str | None = None
    chatbot_url: str
    chatbot_token: str

    knowledge_base_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    owner_email: str | None = None
    created_at: datetime | None = None
    course_count: int | None = None

    prompt_suggestions: list[str] | None = None
    datasource_types: list[str] = []

    avatar_storage_path: str | None = None
    avatar_url: str | None = None

    accent_color: str | None = None
    header_logo_storage_path: str | None = None
    header_logo_url: str | None = None

    reindex_schedule_enabled: bool = False
    reindex_schedule_frequency: str | None = None
    reindex_schedule_day_of_week: int | None = None
    reindex_schedule_day_of_month: int | None = None
    reindex_schedule_hour: int | None = None
    reindex_schedule_minute: int = 0

    chat_request_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class MoodleCourseInfo(BaseModel):
    course_id: str
    course_name: str
    shortname: str | None = None
    description: str | None = None
    category: str | None = None
    course_url: str | None = None
    moodle_domain: str
    selection_key: str
    total_sections: int
    total_activities: int
    model_config = ConfigDict(from_attributes=True)


class ChatbotMoodleCourseInfo(MoodleCourseInfo):
    datasource_id: str
    datasource_name: str
    metadata_synced: bool
    last_metadata_sync: str | None = None
    total_files: int
    model_config = ConfigDict(from_attributes=True)


class ChatbotMoodleCoursesResponse(BaseModel):
    chatbot_id: str
    chatbot_name: str
    knowledge_base_id: str
    linked_moodle_datasources: list[str]
    linked_courses: list[ChatbotMoodleCourseInfo]
    available_courses: list[ChatbotMoodleCourseInfo]
    total_linked: int
    total_available: int
    total_courses: int
    message: str | None = None
    model_config = ConfigDict(from_attributes=True)


class MoodleCoursesListResponse(BaseModel):
    courses: list[MoodleCourseInfo]
    total_courses: int
    returned_courses: int
    has_more: bool
    model_config = ConfigDict(from_attributes=True)


class MoodleCourseFileDetail(BaseModel):
    id: str
    filename: str
    filesize: int = 0
    mimetype: str = ""
    selection_key: str = ""
    download_url: str = ""


class MoodleGlossaryEntryDetail(BaseModel):
    id: str
    concept: str = ""


class MoodleCourseActivityDetail(BaseModel):
    id: str
    name: str
    type: str = "unknown"
    description: str = ""
    files: list[MoodleCourseFileDetail] = []
    entries: list[MoodleGlossaryEntryDetail] = []
    has_indexed_content: bool = False


class MoodleCourseSectionDetail(BaseModel):
    id: str = ""
    name: str
    section_number: int = 0
    summary: str = ""
    activities: list[MoodleCourseActivityDetail] = []
    has_indexed_content: bool = False


class MoodleCourseStructureResponse(BaseModel):
    course_id: str
    course_name: str
    sections: list[MoodleCourseSectionDetail] = []


class MoodleConfigBase(BaseModel):
    datasource_id: UUID


class NextCloudConfigBase(BaseModel):
    datasource_id: UUID


class MoodleConfigCreate(BaseModel):
    domain: str | None = None
    token: str | None = None
    model_config = ConfigDict(from_attributes=True)


class NextCloudConfigCreate(BaseModel):
    url: str | None = None
    username: str | None = None
    password: str | None = None
    model_config = ConfigDict(from_attributes=True)


class MoodleConfig(MoodleConfigBase):
    domain: str
    token: str
    model_config = ConfigDict(from_attributes=True)


class NextCloudConfig(NextCloudConfigBase):
    id: UUID
    username: str
    password: str
    url: str
    model_config = ConfigDict(from_attributes=True)


class DatasourceRespBase(BaseModel):
    """Non-sensitive fields for a datasource response."""

    id: UUID
    name: str
    source_type: int
    owner_id: UUID
    last_sync: datetime | None = None
    sync_status: str = DataSourceSyncStatus.READY
    moodle_config: MoodleConfigBase | None = None
    nextcloud_config: NextCloudConfigBase | None = None
    model_config = ConfigDict(from_attributes=True)


class DataSourceCreate(BaseModel):
    name: str
    source_type: SourceType
    moodle_config: MoodleConfigCreate | None = None
    nextcloud_config: NextCloudConfigCreate | None = None
    model_config = ConfigDict(from_attributes=True)


class DataSourceBaseModel(BaseModel):
    name: str
    source_type: SourceType
    owner_id: UUID
    sync_status: str = DataSourceSyncStatus.READY
    last_sync: datetime | None = None
    last_sync_error: str | None = None


class DataSourceResp(BaseModel):
    id: UUID
    name: str
    source_type: int
    owner_id: UUID
    sync_status: str = DataSourceSyncStatus.READY
    last_sync: datetime | None = None
    last_sync_error: str | None = None
    moodle_config: MoodleConfig | None = None
    nextcloud_config: NextCloudConfig | None = None
    model_config = ConfigDict(from_attributes=True)


class SyncStatus(BaseModel):
    status: str
    last_sync: datetime | None = None
    last_sync_error: str | None = None
