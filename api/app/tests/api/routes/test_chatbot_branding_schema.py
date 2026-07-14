"""Tests for the branding colour validation on ChatbotUpdate.

The chat-interface branding colours must be ``#rrggbb`` hex strings so the
frontend can apply them directly as CSS values. These pin the validator that
rejects anything else while still allowing ``None`` (reset to default).
"""

import pytest
from pydantic import ValidationError

from app.api_v2.routes.chatbots.schemas import ChatbotUpdate


def test_accepts_valid_hex_colors() -> None:
    update = ChatbotUpdate(accent_color="#000000")
    assert update.accent_color == "#000000"


def test_allows_none_to_reset_to_default() -> None:
    update = ChatbotUpdate(accent_color=None)
    assert update.accent_color is None


@pytest.mark.parametrize(
    "bad_value",
    ["232323", "#fff", "#12345g", "red", "#1234567"],
)
def test_rejects_non_hex_colors(bad_value: str) -> None:
    with pytest.raises(ValidationError):
        ChatbotUpdate(accent_color=bad_value)
