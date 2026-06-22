from components.DocumentToRedis import DocumentToRedisComponent
from components.RAGPromptBuilder import RAGPromptBuilder
from config import (
    CHAT_SYSTEM_TEMPLATE,
    EMBED_API_BASE,
    EMBED_API_KEY,
    EMBED_MODEL,
    EMBEDDING_DIM,
    GENERATION_MODEL_ID,
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_ENABLE_THINKING,
    LLM_TEMPERATURE,
    LLM_TOP_K,
    LLM_TOP_P,
    QDRANT_HNSW_CONFIG,
    QDRANT_URL,
    RAG_USER_TEMPLATE,
    SPARSE_EMBED_MODEL,
    TOP_K,
)
from haystack import AsyncPipeline
from haystack.components.embedders import OpenAITextEmbedder
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.utils import Secret
from haystack_integrations.components.embedders.fastembed import (
    FastembedSparseTextEmbedder,
)
from haystack_integrations.components.retrievers.qdrant import (
    QdrantEmbeddingRetriever,
    QdrantHybridRetriever,
)
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from index_config import resolve_sparse_for_index


def create_document_store(
    index_name: str,
    use_sparse: bool | None = None,
    embedding_dim: int | None = None,
) -> QdrantDocumentStore:
    # Match the collection's actual sparse-ness so the store never mismatches
    # and raises. Caller may pass a pre-resolved value to avoid re-inspecting.
    if use_sparse is None:
        use_sparse = resolve_sparse_for_index(index_name)
    return QdrantDocumentStore(
        url=QDRANT_URL,
        index=index_name,
        embedding_dim=embedding_dim or EMBEDDING_DIM,
        recreate_index=False,
        use_sparse_embeddings=use_sparse,
        hnsw_config=QDRANT_HNSW_CONFIG,
    )


def create_rag_pipeline(
    document_store: QdrantDocumentStore,
    session_manager=None,
    embed_model: str | None = None,
    sparse_model: str | None = None,
) -> AsyncPipeline:
    """RAG pipeline: retrieval, prompt building, generation.

    ``embed_model``/``sparse_model`` are the API-dictated embedder identities;
    they fall back to this service's env when not given. They must match what
    the collection was built with.
    """
    pipeline = AsyncPipeline()

    text_embedder = OpenAITextEmbedder(
        api_key=Secret.from_token(EMBED_API_KEY),
        model=embed_model or EMBED_MODEL,
        api_base_url=EMBED_API_BASE,
    )

    if document_store.use_sparse_embeddings:
        pipeline.add_component(
            "sparse_embedder",
            FastembedSparseTextEmbedder(model=sparse_model or SPARSE_EMBED_MODEL),
        )
        pipeline.add_component("dense_embedder", text_embedder)
        pipeline.add_component(
            "retriever",
            QdrantHybridRetriever(document_store=document_store, top_k=TOP_K),
        )
        pipeline.connect(
            "sparse_embedder.sparse_embedding", "retriever.query_sparse_embedding"
        )
        pipeline.connect("dense_embedder.embedding", "retriever.query_embedding")
    else:
        pipeline.add_component("embedder", text_embedder)
        pipeline.add_component(
            "retriever",
            QdrantEmbeddingRetriever(document_store=document_store, top_k=TOP_K),
        )
        pipeline.connect("embedder.embedding", "retriever.query_embedding")

    pipeline.add_component(
        "redis_storage",
        DocumentToRedisComponent(session_manager=session_manager),
    )
    pipeline.connect("retriever.documents", "redis_storage.documents")

    pipeline.add_component(
        "prompt_builder",
        RAGPromptBuilder(
            system_template=CHAT_SYSTEM_TEMPLATE,
            rag_template=RAG_USER_TEMPLATE,
        ),
    )
    pipeline.add_component(
        "llm",
        OpenAIChatGenerator(
            api_key=Secret.from_token(LLM_API_KEY),
            model=GENERATION_MODEL_ID,
            api_base_url=LLM_API_BASE,
            generation_kwargs={
                "temperature": LLM_TEMPERATURE,
                "top_p": LLM_TOP_P,
                "extra_body": {
                    "top_k": LLM_TOP_K,
                    "chat_template_kwargs": {"enable_thinking": LLM_ENABLE_THINKING},
                },
            },
        ),
    )

    pipeline.connect("redis_storage.documents", "prompt_builder.documents")
    pipeline.connect("redis_storage.session_id", "prompt_builder.session_id")
    pipeline.connect("prompt_builder.prompt", "llm.messages")

    return pipeline
