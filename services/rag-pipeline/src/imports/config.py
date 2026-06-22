import os
from pathlib import Path

from dotenv import load_dotenv


def _get_env_from_colab_or_os(key):
    """Get env var from Google Colab userdata or OS."""
    try:
        from google.colab import userdata

        try:
            return userdata.get(key)
        except userdata.SecretNotFoundError:
            pass
    except ImportError:
        pass
    return os.getenv(key)


load_dotenv()

LLM_API_BASE = _get_env_from_colab_or_os("LLM_API_BASE")
LLM_API_KEY = _get_env_from_colab_or_os("LLM_API_KEY") or "no-key"
GENERATION_MODEL_ID = _get_env_from_colab_or_os("GENERATION_MODEL_ID") or "gpt-oss:120b"

LLM_TEMPERATURE = float(_get_env_from_colab_or_os("LLM_TEMPERATURE") or "1.0")
LLM_TOP_P = float(_get_env_from_colab_or_os("LLM_TOP_P") or "0.95")
LLM_TOP_K = int(_get_env_from_colab_or_os("LLM_TOP_K") or "64")
LLM_ENABLE_THINKING = (
    _get_env_from_colab_or_os("LLM_ENABLE_THINKING") or "true"
).lower() in ("true", "1", "yes")

EMBED_API_BASE = _get_env_from_colab_or_os("EMBED_API_BASE") or LLM_API_BASE
EMBED_API_KEY = _get_env_from_colab_or_os("EMBED_API_KEY") or LLM_API_KEY or "no-key"
EMBED_MODEL = _get_env_from_colab_or_os("EMBED_MODEL") or "qwen3-embedding:4b"
EMBEDDING_DIM = int(_get_env_from_colab_or_os("EMBEDDING_DIM") or "2560")

SPARSE_EMBED_MODEL = (
    _get_env_from_colab_or_os("SPARSE_EMBED_MODEL") or "prithvida/Splade_PP_en_v1"
)
# Desired default for NEW/recreated collections. Existing collections keep
# whatever they were built with (resolved per-collection in index_config), so
# flipping this never breaks a collection already in Qdrant.
USE_SPARSE_EMBEDDINGS = (
    _get_env_from_colab_or_os("USE_SPARSE_EMBEDDINGS") or "false"
).lower() in ("true", "1", "yes")

# only affects local docling, not docling-serve
USE_GPU = (_get_env_from_colab_or_os("USE_GPU") or "false").lower() in (
    "true",
    "1",
    "yes",
)

DOCLING_SERVE_URL = (
    _get_env_from_colab_or_os("DOCLING_SERVE_URL") or "http://docling:5001"
)
DOCLING_SERVE_API_KEY = _get_env_from_colab_or_os("DOCLING_SERVE_API_KEY")
DOCLING_SERVE_TIMEOUT = float(
    _get_env_from_colab_or_os("DOCLING_SERVE_TIMEOUT") or "300"
)
DOCLING_OCR_ENGINE = _get_env_from_colab_or_os("DOCLING_OCR_ENGINE") or "easyocr"
DOCLING_OCR_LANG = (_get_env_from_colab_or_os("DOCLING_OCR_LANG") or "en,fr,de").split(
    ","
)
DOCLING_PDF_BACKEND = (
    _get_env_from_colab_or_os("DOCLING_PDF_BACKEND") or "docling_parse"
)
DOCLING_TABLE_MODE = _get_env_from_colab_or_os("DOCLING_TABLE_MODE") or "accurate"
DOCLING_DOCUMENT_TIMEOUT = float(
    _get_env_from_colab_or_os("DOCLING_DOCUMENT_TIMEOUT") or "240"
)

INGEST_FOLDER = Path("ingest")

TOP_K = 6

# tokenizer should match embedding model family
CHUNKER_TOKENIZER = "Qwen/Qwen2.5-0.5B"
CHUNKER_MAX_TOKENS = 1024

QDRANT_URL = "qdrant"
QDRANT_INDEX = "Document"
QDRANT_HNSW_CONFIG = {"m": 16, "ef_construct": 64}

REDIS_URL = _get_env_from_colab_or_os("REDIS_URL") or "redis://redis:6379/0"
SESSION_TTL = int(_get_env_from_colab_or_os("SESSION_TTL") or "3600")
JOB_TTL = int(_get_env_from_colab_or_os("JOB_TTL") or "3600")

ENABLE_SESSION_STORAGE = _get_env_from_colab_or_os("ENABLE_SESSION_STORAGE") or "true"
SESSION_STORAGE_ENABLED = ENABLE_SESSION_STORAGE.lower() in ("true", "1", "yes")

# Jinja2, rendered with persona and cite_sources variables
CHAT_SYSTEM_TEMPLATE = """{{ persona if persona else "You are a helpful assistant." }}

Rules:
- Questions about your identity, role, or capabilities should always be answered from your persona above, regardless of what the sources contain.
- Respond in the same language as the user.
- Be concise. Answer the question directly without repeating yourself or summarizing at the end.
{% if cite_sources %}- When using information from sources, cite them using [1], [2], etc. corresponding to the source id. Place citations inline at the end of the relevant sentence or claim. When multiple sources support the same sentence, write each id in its own brackets back-to-back, e.g. [1][3]: never combine them as [1,3] or [1-3]. Do not add a bibliography or source list at the end of your response.
{% endif %}- If the source material appears unreadable or low quality, mention it and answer as best you can."""

RAG_USER_TEMPLATE = """<context>
{% if documents %}{% for doc in documents %}<source id="{{ loop.index }}" file="{{ doc.meta.get('file_name', doc.meta.get('source', 'unknown')) }}"{% if doc.meta.get('headings') %} section="{{ doc.meta.get('headings', []) | join(' > ') }}"{% endif %}>
{{ doc.content }}
</source>
{% endfor %}{% else %}No context available.{% endif %}</context>

{{ query }}"""


def get_ingest_files():
    """List files in the ingest folder."""
    if not INGEST_FOLDER.exists():
        raise FileNotFoundError(f"Ingest folder '{INGEST_FOLDER}' does not exist")

    files = [
        str(file_path) for file_path in INGEST_FOLDER.iterdir() if file_path.is_file()
    ]

    if not files:
        raise ValueError(f"No files found in '{INGEST_FOLDER}' folder")

    return files
