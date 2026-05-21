from typing import Any

from config import CHAT_SYSTEM_TEMPLATE, RAG_USER_TEMPLATE
from haystack import component
from haystack.dataclasses import ChatMessage
from jinja2 import Template


@component
class RAGPromptBuilder:
    """Build prompts with conversation history and document context."""

    def __init__(self, system_template: str = None, rag_template: str = None):
        self.default_system_template = system_template or CHAT_SYSTEM_TEMPLATE
        self.default_rag_template = rag_template or RAG_USER_TEMPLATE

    @component.output_types(prompt=list[ChatMessage], citations=list[dict[str, Any]])
    def run(
        self,
        query: str,
        documents: list[Any] = None,
        conversation_history: list[ChatMessage] | None = None,
        session_id: str | None = None,
        system_prompt: str | None = None,
        rag_template: str | None = None,
        cite_sources: bool = True,
    ) -> dict[str, Any]:
        """Build messages with system prompt, history, and current query.

        :param system_prompt: persona text rendered into the system template as
            ``persona``. Not used as a raw system message.
        :param cite_sources: include citation instructions in the system prompt.
        """
        active_rag_template = rag_template or self.default_rag_template

        system_template = Template(self.default_system_template)
        rendered_system = system_template.render(
            persona=system_prompt or "", cite_sources=cite_sources
        )

        messages = [ChatMessage.from_system(rendered_system)]

        if conversation_history:
            messages.extend(conversation_history)

        docs = documents or []

        template = Template(active_rag_template)
        current_query = template.render(documents=docs, query=query)

        messages.append(ChatMessage.from_user(current_query))

        # citations are 1-indexed to match source ids in the prompt
        citations = []
        for i, doc in enumerate(docs):
            meta = doc.meta if hasattr(doc, "meta") else {}
            citations.append(
                {
                    "id": i + 1,
                    "file_name": meta.get("file_name", meta.get("source", "unknown")),
                    "chunk_index": meta.get("chunk_index"),
                    "total_chunks": meta.get("total_chunks"),
                    "headings": meta.get("headings", []),
                }
            )

        return {"prompt": messages, "citations": citations}
