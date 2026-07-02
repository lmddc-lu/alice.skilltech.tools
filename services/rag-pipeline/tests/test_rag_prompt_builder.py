"""Unit tests for RAGPromptBuilder."""

from __future__ import annotations

import pytest

from tests.conftest import StubChatMessage, StubDocument


@pytest.fixture
def builder_cls():
    from RAGPromptBuilder import RAGPromptBuilder

    return RAGPromptBuilder


def _doc(content: str, **meta) -> StubDocument:
    return StubDocument(content=content, meta=meta)


class TestRAGPromptBuilder:
    def test_default_system_prompt_uses_helpful_assistant(self, builder_cls):
        builder = builder_cls()
        result = builder.run(query="hi")

        messages = result["prompt"]
        assert messages[0].role == "system"
        assert messages[-1].role == "user"
        assert "You are a helpful assistant." in messages[0].content

    def test_persona_is_injected_into_system_prompt(self, builder_cls):
        builder = builder_cls()
        result = builder.run(query="hi", system_prompt="You are a SCORM expert.")

        assert "You are a SCORM expert." in result["prompt"][0].content
        # default fallback must not appear when persona is set
        assert "You are a helpful assistant." not in result["prompt"][0].content

    def test_cite_sources_true_includes_citation_rule(self, builder_cls):
        builder = builder_cls()
        result = builder.run(query="hi", cite_sources=True)
        assert "Cite them using [1], [2]" in result["prompt"][0].content

    def test_cite_sources_false_omits_citation_rule(self, builder_cls):
        builder = builder_cls()
        result = builder.run(query="hi", cite_sources=False)
        assert "cite them using" not in result["prompt"][0].content

    def test_documents_are_rendered_as_sources_with_index(self, builder_cls):
        builder = builder_cls()
        docs = [
            _doc("first chunk", file_name="a.pdf"),
            _doc("second chunk", file_name="b.pdf", headings=["Intro", "Goals"]),
        ]
        result = builder.run(query="What is X?", documents=docs)

        user_content = result["prompt"][-1].content
        assert '<source id="1" file="a.pdf"' in user_content
        assert '<source id="2" file="b.pdf"' in user_content
        assert "first chunk" in user_content
        assert "second chunk" in user_content
        assert 'section="Intro > Goals"' in user_content
        assert "What is X?" in user_content

    def test_no_documents_renders_no_context_message(self, builder_cls):
        builder = builder_cls()
        result = builder.run(query="hi", documents=[])
        assert "No context available." in result["prompt"][-1].content

    def test_conversation_history_is_inserted_between_system_and_user(
        self, builder_cls
    ):
        builder = builder_cls()
        history = [
            StubChatMessage("user", "earlier question"),
            StubChatMessage("assistant", "earlier answer"),
        ]
        result = builder.run(query="follow up", conversation_history=history)

        roles = [m.role for m in result["prompt"]]
        assert roles == ["system", "user", "assistant", "user"]
        assert result["prompt"][1].content == "earlier question"
        assert result["prompt"][2].content == "earlier answer"

    def test_citations_have_one_based_indices(self, builder_cls):
        builder = builder_cls()
        docs = [
            _doc(
                "a", file_name="a.pdf", chunk_index=0, total_chunks=2, headings=["H1"]
            ),
            _doc("b", source="b.txt"),  # falls back to source then unknown
        ]
        result = builder.run(query="q", documents=docs)

        cites = result["citations"]
        assert len(cites) == 2
        assert cites[0]["id"] == 1
        assert cites[0]["file_name"] == "a.pdf"
        assert cites[0]["chunk_index"] == 0
        assert cites[0]["total_chunks"] == 2
        assert cites[0]["headings"] == ["H1"]
        assert cites[1]["id"] == 2
        assert cites[1]["file_name"] == "b.txt"
        assert cites[1]["headings"] == []

    def test_custom_rag_template_is_honoured(self, builder_cls):
        builder = builder_cls()
        result = builder.run(
            query="q",
            documents=[_doc("c1")],
            rag_template="Q: {{ query }} || COUNT: {{ documents | length }}",
        )
        assert result["prompt"][-1].content == "Q: q || COUNT: 1"
