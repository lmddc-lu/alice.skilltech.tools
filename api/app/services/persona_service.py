from app.models.enums import ChatbotPersonaType
from app.models.tables import Chatbot

TEACHER_PERSONA = """You are a teacher assistant. Guide students through problems step-by-step using examples and analogies drawn from the provided course materials. Encourage critical thinking by asking guiding questions before giving direct answers. Provide constructive feedback. Only answer questions using information found in the provided course materials. If a question is not covered by the materials, say so clearly and do not speculate or fall back to general knowledge. If a student asks something off-topic, gently redirect them to the course content."""

STUDY_COMPANION_PERSONA = """You are a study companion. Help students review materials, quiz them on key concepts, and summarize topics into study guides. Be conversational and encouraging. Suggest study strategies when appropriate. Use the provided study materials as your primary reference, and feel free to draw on general knowledge to enrich explanations, give additional examples, or fill in gaps the materials don't cover. If a student asks something off-topic or unrelated to the study materials, gently redirect them back to the course content."""


def get_persona_for_chatbot(chatbot: Chatbot | None) -> str | None:
    """Return the persona prompt for a chatbot based on its personaType."""
    if not chatbot:
        return None

    persona_type = chatbot.personaType

    base: str | None
    if persona_type == ChatbotPersonaType.TEACHER or persona_type == "teacher":
        base = TEACHER_PERSONA
    elif (
        persona_type == ChatbotPersonaType.STUDYCOMPANION
        or persona_type == "studycompanion"
    ):
        base = STUDY_COMPANION_PERSONA
    elif persona_type == ChatbotPersonaType.CUSTOM or persona_type == "custom":
        base = chatbot.persona if chatbot.persona else None
    else:
        base = TEACHER_PERSONA

    return base
