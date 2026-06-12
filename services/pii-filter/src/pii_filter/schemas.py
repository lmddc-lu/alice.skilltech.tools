from pydantic import BaseModel, Field


class RedactRequest(BaseModel):
    text: str = Field(..., description="Text to scan for PII")
    min_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Drop entities below this confidence score",
    )


class Entity(BaseModel):
    type: str = Field(..., description="Entity label (e.g. FIRST_NAME, EMAIL)")
    start: int = Field(..., description="Start offset in the original text")
    end: int = Field(..., description="End offset (exclusive) in the original text")
    score: float = Field(..., description="Model confidence in [0, 1]")
    surface: str = Field(..., description="Surface form as it appears in the text")


class RedactResponse(BaseModel):
    redacted_text: str = Field(
        ...,
        description=(
            "Text with detected PII replaced by [TYPE_N] placeholders. Numbering "
            "is per-call and per-type; identical surface forms within a call share "
            "the same number. Callers maintaining a session-wide map should use "
            "the entity spans directly rather than this string."
        ),
    )
    entities: list[Entity]
    mapping: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Maps each [TYPE_N] placeholder back to the original surface form, so "
            "callers can reverse the redaction (e.g. un-redact an LLM response "
            "that echoes a placeholder)."
        ),
    )


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_name: str | None = None
    device: str | None = None
