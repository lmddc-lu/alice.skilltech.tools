"""Request/response models used only by the chatbots endpoints."""

import re
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ChatbotPersonaType, ReindexFrequency

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


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
    pii_filter_enabled: bool | None = None
    # Chat-interface branding. Admin-only; enforced in the update endpoint.
    accent_color: str | None = None

    @field_validator("accent_color")
    @classmethod
    def _validate_hex_color(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError("Color must be a #rrggbb hex string")
        return value


class ChatbotAccessRequest(BaseModel):
    password: str | None = None


class ChatRequest(BaseModel):
    password: str | None = None
    messages: list[dict[str, str]]
    # Opt-in for the owner/admin retrieved-chunks debug view. Only the editor's
    # preview window sets this; honored only when the caller is owner/admin.
    debug: bool = False


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
