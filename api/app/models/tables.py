import uuid
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ConfigDict
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import (
    ChatbotAccessLevel,
    ChatbotPersonaType,
    CourseSyncState,
    DataSourceSyncStatus,
    FileStatus,
    JobFileState,
    JobStatus,
    KnowledgeBaseStatus,
    UserRole,
)


class UserBase(SQLModel):
    email: str = Field(unique=True, max_length=255)
    is_active: bool = Field(default=True)
    role: str = Field(default=UserRole.USER)
    name: str | None = Field(default=None, max_length=255)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider_id: str = Field(default="")
    knowledge_bases: list["KnowledgeBase"] = Relationship(back_populates="user")
    chat_sessions: list["ChatSession"] = Relationship(back_populates="user")
    datasources: list["DataSource"] = Relationship(back_populates="owner")


class KnowledgeBaseDatasourceLink(SQLModel, table=True):
    knowledge_base_id: uuid.UUID = Field(
        foreign_key="knowledgebase.id", primary_key=True
    )
    datasource_id: uuid.UUID = Field(foreign_key="datasource.id", primary_key=True)
    selection: str = Field(default="")


class DataSourceBase(SQLModel):
    name: str
    source_type: int
    sync_status: str = DataSourceSyncStatus.READY
    last_sync: datetime | None = None
    last_sync_error: str | None = None


class DataSource(DataSourceBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(foreign_key="user.id")

    owner: User = Relationship(back_populates="datasources")
    knowledge_bases: list["KnowledgeBase"] = Relationship(
        back_populates="datasources", link_model=KnowledgeBaseDatasourceLink
    )
    moodle_config: "MoodleDataSourceConfig" = Relationship(back_populates="datasource")
    nextcloud_config: "NextCloudDataSourceConfig" = Relationship(
        back_populates="datasource"
    )
    uploaded_files: list["UploadedFile"] = Relationship(back_populates="datasource")


class MoodleDataSourceConfig(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    datasource_id: uuid.UUID = Field(foreign_key="datasource.id", unique=True)
    domain: str
    token: str

    datasource: DataSource = Relationship(back_populates="moodle_config")
    moodle_courses: list["MoodleCourse"] = Relationship(
        back_populates="datasource_config",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class MoodleCourse(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    datasource_config_id: uuid.UUID = Field(foreign_key="moodledatasourceconfig.id")
    moodle_course_id: str = Field(index=True)
    moodle_course_name: str
    moodle_course_files: str

    metadata_last_sync: datetime | None = None
    metadata_version: str | None = None
    content_last_sync: datetime | None = None
    content_sync_status: str = Field(default=CourseSyncState.NOT_SYNCED)
    content_sync_error: str | None = None

    sections_downloaded: int = Field(default=0)
    activities_downloaded: int = Field(default=0)
    total_sections: int = Field(default=0)
    total_activities: int = Field(default=0)

    datasource_config: MoodleDataSourceConfig = Relationship(
        back_populates="moodle_courses"
    )
    model_config = ConfigDict(  # type: ignore[assignment,typeddict-unknown-key]
        table=True,
        sa_table_args=(UniqueConstraint("datasource_config_id", "moodle_course_id"),),
    )


class UploadedFile(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    datasource_id: uuid.UUID = Field(foreign_key="datasource.id")

    original_filename: str
    stored_filename: str
    file_size: int
    mime_type: str
    file_hash: str
    storage_path: str = Field(default="")

    tags: str = Field(default="")

    # true when this row is free-text the user typed in the manage-files
    # dialog rather than an actual upload. drives inline edit on the frontend.
    is_free_text: bool = Field(default=False)

    status: FileStatus = Field(default=FileStatus.UPLOADING)
    upload_date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    processed_date: datetime | None = None

    extracted_text_length: int = Field(default=0)
    processing_error: str | None = None

    datasource: DataSource = Relationship(back_populates="uploaded_files")


class NextCloudDataSourceConfig(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    datasource_id: uuid.UUID = Field(foreign_key="datasource.id", unique=True)
    url: str
    username: str
    password: str

    datasource: DataSource = Relationship(back_populates="nextcloud_config")


class KnowledgeBaseBase(SQLModel):
    name: str
    description: str | None = None
    status: str = KnowledgeBaseStatus.READY
    last_sync: datetime | None = None
    last_sync_error: str | None = None


class KnowledgeBase(KnowledgeBaseBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id")
    user: User = Relationship(back_populates="knowledge_bases")
    datasources: list[DataSource] = Relationship(
        back_populates="knowledge_bases", link_model=KnowledgeBaseDatasourceLink
    )
    chatbots: list["Chatbot"] = Relationship(back_populates="knowledge_base")


class ChatbotBase(SQLModel):
    name: str
    description: str | None = None
    access_level: str = Field(default=ChatbotAccessLevel.PRIVATE)
    knowledge_base_id: uuid.UUID = Field(foreign_key="knowledgebase.id")
    datasource_types: str = Field(default="")
    personaType: str = Field(default=ChatbotPersonaType.TEACHER)
    persona: str | None = None
    prompt_suggestions: str | None = None
    cite_sources: bool = Field(default=True)
    force_ocr: bool = Field(default=False)
    persist_session: bool = Field(default=False)
    pii_filter_enabled: bool = Field(default=False)
    avatar_storage_path: str | None = Field(default=None, max_length=1024)

    # scheduled reindex. frequency is a ReindexFrequency value.
    # weekly uses day_of_week (0=Mon..6=Sun, APScheduler convention).
    # monthly uses day_of_month (1..28, capped to avoid short months).
    reindex_schedule_enabled: bool = Field(default=False)
    reindex_schedule_frequency: str | None = Field(default=None)
    reindex_schedule_day_of_week: int | None = Field(default=None)
    reindex_schedule_day_of_month: int | None = Field(default=None)
    reindex_schedule_hour: int | None = Field(default=None)
    reindex_schedule_minute: int = Field(default=0)


class Chatbot(ChatbotBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    password_hash: str | None = Field(default=None)
    enabled: bool = Field(default_factory=lambda: True)
    token: str = Field(default_factory=lambda: str(uuid.uuid4()).replace("-", ""))
    api_enabled: bool = Field(default=False)
    chat_request_count: int = Field(default=0)

    knowledge_base: KnowledgeBase = Relationship(back_populates="chatbots")
    chat_sessions: list["ChatSession"] = Relationship(back_populates="chatbot")
    owner: User = Relationship()


class OAuthSession(SQLModel, table=True):
    """OAuth session tracking for OIDC."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: UUID | None = Field(default=None, foreign_key="user.id")
    provider: str = Field(default="oidc")

    # CSRF protection
    state: str = Field(unique=True)
    nonce: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    provider_user_id: str | None = None
    email: str | None = None
    name: str | None = None


class MoodleIntegrationBase(SQLModel):
    name: str = Field(
        max_length=255, description="Display name for this Moodle instance"
    )
    moodle_url: str = Field(description="The Moodle instance URL")
    default_chatbot_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="chatbot.id",
        description="Default chatbot to use when no course mapping exists",
    )
    is_active: bool = Field(
        default=True, description="Whether this integration is active"
    )


class MoodleIntegration(MoodleIntegrationBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    token: str = Field(
        unique=True,
        default_factory=lambda: str(uuid.uuid4()).replace("-", ""),
        description="Authentication token for this Moodle instance",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    default_chatbot: Chatbot | None = Relationship()
    course_mappings: list["MoodleCourseChatbotMapping"] = Relationship(
        back_populates="moodle_integration",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class MoodleCourseChatbotMappingBase(SQLModel):
    course_id: str = Field(description="The Moodle course ID")
    chatbot_id: uuid.UUID = Field(description="The chatbot to use for this course")


class MoodleCourseChatbotMapping(MoodleCourseChatbotMappingBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    moodle_integration_id: uuid.UUID = Field(foreign_key="moodleintegration.id")
    course_id: str = Field()  # external id, no FK
    chatbot_id: uuid.UUID = Field(foreign_key="chatbot.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    moodle_integration: MoodleIntegration = Relationship(
        back_populates="course_mappings"
    )
    chatbot: Chatbot = Relationship()
    model_config = ConfigDict(  # type: ignore[assignment,typeddict-unknown-key]
        table=True,
        sa_table_args=(UniqueConstraint("moodle_integration_id", "course_id"),),
    )


class ChatSessionBase(SQLModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_message_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    title: str | None = None


class ChatSession(ChatSessionBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    chatbot_id: uuid.UUID = Field(foreign_key="chatbot.id")
    user_id: uuid.UUID = Field(foreign_key="user.id")

    chatbot: Chatbot = Relationship(back_populates="chat_sessions")
    user: User = Relationship(back_populates="chat_sessions")
    messages: list["ChatMessage"] = Relationship(
        back_populates="chat_session",
        sa_relationship_kwargs={"order_by": "ChatMessage.created_at"},
    )


class ChatMessageBase(SQLModel):
    role: str = Field(index=True)
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    tokens_used: int | None = None
    processing_time: float | None = None
    error: bool = Field(default=False)


class ChatMessage(ChatMessageBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    chat_session_id: uuid.UUID = Field(foreign_key="chatsession.id")

    chat_session: ChatSession = Relationship(back_populates="messages")


class Job(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    job_type: str = Field(index=True)  # JobType value
    status: str = Field(default=JobStatus.PENDING, index=True)

    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    datasource_id: uuid.UUID | None = Field(default=None, index=True)
    knowledge_base_id: uuid.UUID | None = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    # last progress update (per-file or aggregate). drives stale-job
    # detection independently of started_at.
    progress_updated_at: datetime | None = None

    # denormalized counters from JobFile rows for fast status reads
    progress_current: int = Field(default=0)
    progress_total: int = Field(default=0)
    progress_message: str | None = None

    result_summary: str | None = None  # JSON
    error_message: str | None = None
    error_details: str | None = None  # full traceback

    input_params: str | None = None  # JSON
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=3)


class JobFile(SQLModel, table=True):
    """Per-file progress record for a Job."""

    __table_args__ = (
        UniqueConstraint("job_id", "external_file_id", name="uq_jobfile_job_extid"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(foreign_key="job.id", index=True)

    external_file_id: str = Field(index=True)
    filename: str
    state: str = Field(default=JobFileState.PENDING.value, index=True)
    error_message: str | None = None
    # verbose technical detail (e.g. Docling/converter error). not shown in
    # user-facing UI, admin job detail surfaces it for triage.
    error_detail: str | None = None
    # JobFileErrorCode value, NULL when unclassified
    error_code: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobEvent(SQLModel, table=True):
    """Audit log for job state changes."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(foreign_key="job.id", index=True)

    event_type: str  # status_change, progress_update, error, retry
    old_status: str | None = None
    new_status: str | None = None
    message: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
