import time
from collections.abc import AsyncGenerator
from typing import Any

from config import (
    QDRANT_INDEX,
    REDIS_URL,
    SESSION_STORAGE_ENABLED,
    SESSION_TTL,
    TOP_K,
    USE_SPARSE_EMBEDDINGS,
)
from fastapi import HTTPException
from hayhooks import (
    BasePipelineWrapper,
    async_streaming_generator,
    get_last_user_message,
)
from haystack.dataclasses import ChatMessage
from index_config import resolve_embedding_config, resolve_sparse_for_index
from loguru import logger
from RedisSessionManager import RedisSessionManager

from .pipeline_builder import create_document_store, create_rag_pipeline


class RAGPipelineWrapper(BasePipelineWrapper):
    """RAG query pipeline."""

    def setup(self) -> None:
        self._default_index = QDRANT_INDEX

        self.session_manager = None
        if SESSION_STORAGE_ENABLED:
            try:
                self.session_manager = RedisSessionManager(
                    redis_url=REDIS_URL, session_ttl=SESSION_TTL
                )
                logger.info("Valkey session storage enabled")
            except Exception as e:
                logger.warning(f"Failed to initialize Valkey session manager: {e}")
                logger.info("Session storage disabled, sources will not be cached")

        logger.info(
            f"RAG Pipeline initialized with hybrid search: {USE_SPARSE_EMBEDDINGS}"
        )
        logger.info(f"Session storage enabled: {SESSION_STORAGE_ENABLED}")

    def _get_pipeline(self, index_name: str = None, embedding_config=None):
        """Build a per-request pipeline. Returns (pipeline, use_sparse) so the
        caller can shape pipeline inputs to match the collection's retriever.

        ``embedding_config`` is the API-dictated config (dict or JSON string);
        it falls back to this service's env when absent.
        """
        name = index_name or self._default_index
        cfg = resolve_embedding_config(embedding_config)
        # an existing collection's actual sparse-ness wins; the dictated config
        # is the desired default for a not-yet-built collection.
        use_sparse = resolve_sparse_for_index(
            name, desired_sparse=bool(cfg["sparse_model"])
        )
        document_store = create_document_store(
            name, use_sparse=use_sparse, embedding_dim=cfg["dim"]
        )
        pipeline = create_rag_pipeline(
            document_store,
            self.session_manager,
            embed_model=cfg["model"],
            sparse_model=cfg["sparse_model"],
        )
        return pipeline, use_sparse

    def _convert_history_to_messages(
        self, conversation_history: list[dict[str, str]] | None
    ) -> list[ChatMessage]:
        if not conversation_history:
            return []

        messages = []
        for msg in conversation_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                messages.append(ChatMessage.from_user(content))
            elif role == "assistant":
                messages.append(ChatMessage.from_assistant(content))
            elif role == "system":
                messages.append(ChatMessage.from_system(content))
            else:
                messages.append(ChatMessage.from_user(content))

        return messages

    def _prepare_pipeline_inputs(
        self,
        question: str,
        chat_messages: list[ChatMessage],
        session_id: str | None = None,
        system_prompt: str | None = None,
        rag_template: str | None = None,
        cite_sources: bool = True,
        use_sparse: bool = False,
    ) -> dict[str, Any]:
        pipeline_inputs = {
            "prompt_builder": {
                "query": question,
                "conversation_history": chat_messages,
                "cite_sources": cite_sources,
            },
            "redis_storage": {"session_id": session_id},
        }

        if system_prompt is not None:
            pipeline_inputs["prompt_builder"]["system_prompt"] = system_prompt
        if rag_template is not None:
            pipeline_inputs["prompt_builder"]["rag_template"] = rag_template

        if use_sparse:
            pipeline_inputs["sparse_embedder"] = {"text": question}
            pipeline_inputs["dense_embedder"] = {"text": question}
        else:
            pipeline_inputs["embedder"] = {"text": question}

        return pipeline_inputs

    async def run_chat_completion_async(
        self, model: str, messages: list[dict], body: dict
    ) -> AsyncGenerator:
        """OpenAI-compatible async chat completion endpoint."""
        try:
            top_k = body.get("top_k", TOP_K)
            index_name = body.get("index_name", None)
            custom_chat_id = body.get("custom_id")
            system_prompt = body.get("system_prompt")
            rag_template = body.get("rag_template")
            cite_sources = body.get("cite_sources", True)
            embedding_config = body.get("embedding_config")

            if not custom_chat_id:
                timestamp = int(time.time() * 1000)
                custom_chat_id = f"{model}-{timestamp}"

            question = get_last_user_message(messages)

            # everything except the last message becomes conversation history
            conversation_history = []
            if len(messages) > 1:
                for msg in messages[:-1]:
                    if msg.get("role") in ["user", "assistant"]:
                        conversation_history.append(
                            {"role": msg.get("role"), "content": msg.get("content", "")}
                        )

            pipeline, use_sparse = self._get_pipeline(index_name, embedding_config)

            retriever = pipeline.get_component("retriever")
            if hasattr(retriever, "top_k") and retriever.top_k != top_k:
                retriever.top_k = top_k

            chat_messages = self._convert_history_to_messages(conversation_history)
            pipeline_inputs = self._prepare_pipeline_inputs(
                question,
                chat_messages,
                custom_chat_id,
                system_prompt,
                rag_template,
                cite_sources,
                use_sparse=use_sparse,
            )

            return async_streaming_generator(
                pipeline=pipeline, pipeline_run_args=pipeline_inputs
            )

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail={
                    "success": False,
                    "error": str(e),
                    "processed_files": 0,
                    "index_name": index_name or self._default_index,
                    "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
                },
            ) from e

    async def run_api_async(
        self,
        question: str,
        top_k: int | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        index_name: str | None = None,
        system_prompt: str | None = None,
        rag_template: str | None = None,
        cite_sources: bool = True,
        embedding_config: dict | str | None = None,
    ) -> dict[str, Any]:
        """Answer a question with document context."""
        if top_k is None:
            top_k = TOP_K

        try:
            pipeline, use_sparse = self._get_pipeline(index_name, embedding_config)

            retriever = pipeline.get_component("retriever")
            if hasattr(retriever, "top_k") and retriever.top_k != top_k:
                retriever.top_k = top_k

            chat_messages = self._convert_history_to_messages(conversation_history)
            pipeline_inputs = self._prepare_pipeline_inputs(
                question,
                chat_messages,
                system_prompt=system_prompt,
                rag_template=rag_template,
                cite_sources=cite_sources,
                use_sparse=use_sparse,
            )

            result = await pipeline.run_async(
                pipeline_inputs,
                include_outputs_from={"llm", "redis_storage", "prompt_builder"},
            )

            llm_replies = result.get("llm", {}).get("replies", [])
            redis_result = result.get("redis_storage", {})
            prompt_builder_result = result.get("prompt_builder", {})

            answer_text = ""
            if llm_replies and len(llm_replies) > 0:
                answer_text = llm_replies[0].text

            session_id = redis_result.get("session_id")
            documents = redis_result.get("documents", [])
            citations = prompt_builder_result.get("citations", [])

            response = {
                "success": True,
                "answer": answer_text,
                "citations": citations,
                "session_id": session_id,
                "question": question,
                "index_name": index_name or self._default_index,
                "conversation_history": conversation_history,
                "hybrid_search_enabled": use_sparse,
                "retrieved_documents": len(documents),
                "top_k": top_k,
                "session_storage_enabled": SESSION_STORAGE_ENABLED,
            }

            if system_prompt is not None:
                response["custom_system_prompt"] = True
            if rag_template is not None:
                response["custom_rag_template"] = True

            return response

        except Exception as e:
            logger.exception(f"Error in RAG pipeline: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "success": False,
                    "error": str(e),
                    "processed_files": 0,
                    "index_name": index_name or self._default_index,
                    "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
                },
            ) from e


PipelineWrapper = RAGPipelineWrapper
