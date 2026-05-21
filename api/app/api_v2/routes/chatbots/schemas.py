"""Request/response models used only by the chatbots endpoints."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ChatbotPersonaType, ReindexFrequency


class TextEntryContentResponse(BaseModel):
    id: UUID
    title: str
    content: str


class ChatbotUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    persona: str | None = None
    personaType: ChatbotPersonaType | None = None
    password: str | None = None
    enabled: bool | None = None
    access_level: str | None = None
    api_enabled: bool | None = None
    prompt_suggestions: list[str] | None = None
    cite_sources: bool | None = None
    force_ocr: bool | None = None
    persist_session: bool | None = None


class ChatbotAccessRequest(BaseModel):
    password: str | None = None


class ChatRequest(BaseModel):
    password: str | None = None
    messages: list[dict[str, str]]


class UpdateMoodleCoursesRequest(BaseModel):
    course_ids: list[str] = Field(
        default_factory=list,
        description="Complete list of course IDs to be linked (e.g., ['3', '5', '7'])",
    )


class ReindexScheduleRequest(BaseModel):
    """Chatbot reindex schedule. Weekly needs day_of_week, monthly needs day_of_month."""

    enabled: bool = Field(
        description="Whether the schedule is active. When False, the other "
        "fields are ignored."
    )
    frequency: ReindexFrequency | None = Field(
        default=None,
        description="Cadence: 'weekly' or 'monthly'. Required when enabled.",
    )
    day_of_week: int | None = Field(
        default=None,
        ge=0,
        le=6,
        description="Day of the week, 0=Monday ... 6=Sunday (APScheduler convention). "
        "Required for weekly frequency.",
    )
    day_of_month: int | None = Field(
        default=None,
        ge=1,
        le=28,
        description="Day of the month (1-28, capped to avoid short-month edge "
        "cases). Required for monthly frequency.",
    )
    hour: int | None = Field(
        default=None,
        ge=0,
        le=23,
        description="Hour of the day in the server timezone (0-23).",
    )
    minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Minute within the hour (0-59).",
    )


class ReindexScheduleResponse(BaseModel):
    chatbot_id: UUID
    enabled: bool
    frequency: ReindexFrequency | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    hour: int | None = None
    minute: int = 0
