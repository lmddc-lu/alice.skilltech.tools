"""Per-collection resolution of sparse (hybrid) vs dense retrieval.

``USE_SPARSE_EMBEDDINGS`` is only the *desired default* for collections that are
created or recreated from now on. Existing collections must keep being queried
and written with whatever they were actually built with: the Qdrant document
store raises on init if ``use_sparse_embeddings`` disagrees with the collection
(dense store vs sparse collection, or vice versa). So a single global flip would
break every pre-existing collection at once.

This module resolves the right value per collection by inspecting Qdrant: a
collection that exists is matched to its real sparse-ness; a missing or
recreated one uses the desired default. That lets dense and sparse collections
coexist while sparse is rolled out one reindex at a time.
"""

from __future__ import annotations

import json
import threading

from config import (
    EMBED_MODEL,
    EMBEDDING_DIM,
    QDRANT_URL,
    SPARSE_EMBED_MODEL,
    USE_SPARSE_EMBEDDINGS,
)
from loguru import logger

_client = None
_client_lock = threading.Lock()


def _get_client():
    """Lazily build a raw Qdrant client, reusing the document store's own
    connection parameters so it works for every supported QDRANT_URL form.

    Heavy imports are deferred here so this module stays importable (and the
    resolver logic stays unit-testable) without qdrant installed.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import qdrant_client
                from haystack_integrations.document_stores.qdrant import (
                    QdrantDocumentStore,
                )

                probe = QdrantDocumentStore(
                    url=QDRANT_URL,
                    index="__resolver_probe__",
                    embedding_dim=EMBEDDING_DIM,
                    recreate_index=False,
                )
                _client = qdrant_client.QdrantClient(**probe._prepare_client_params())
    return _client


def collection_has_sparse(index_name: str) -> bool | None:
    """Whether a collection has named sparse vectors.

    Returns True/False if the collection exists, or None if it does not exist
    (or could not be inspected) so the caller can fall back to the default.
    """
    try:
        client = _get_client()
        if not client.collection_exists(index_name):
            return None
        info = client.get_collection(index_name)
        return bool(info.config.params.sparse_vectors)
    except Exception as e:
        logger.warning(f"Could not inspect collection '{index_name}' for sparse: {e}")
        return None


def resolve_sparse_for_index(
    index_name: str, recreate: bool = False, desired_sparse: bool | None = None
) -> bool:
    """Resolve whether to build/query ``index_name`` with sparse embeddings.

    - ``recreate`` (or a brand-new collection): use the desired default — this
      is how a forced reindex migrates a collection to the new config.
    - an existing collection: match whatever it was actually built with, so the
      document store never mismatches and raises.

    ``desired_sparse`` overrides the env default when the caller (the API) has
    dictated the config for this request; ``None`` falls back to the env
    ``USE_SPARSE_EMBEDDINGS``.
    """
    desired = USE_SPARSE_EMBEDDINGS if desired_sparse is None else desired_sparse
    if recreate:
        return desired
    detected = collection_has_sparse(index_name)
    return desired if detected is None else detected


def parse_embedding_config(value) -> dict | None:
    """Normalise a passed embedding config (dict or JSON string) to a dict.

    Returns None when nothing usable was passed, so callers fall back to env.
    """
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as e:
            logger.warning(f"Ignoring unparseable embedding_config: {e}")
            return None
    return value if isinstance(value, dict) else None


def resolve_embedding_config(passed=None) -> dict:
    """Resolve the embedding config to build/query with.

    The API dictates the config per request (single source of truth). When a
    field is absent — or nothing is passed at all (direct curl, older caller) —
    fall back to this service's env, so the pipeline stays usable standalone.

    Returns ``{model, dim, distance, sparse_model}``. ``sparse_model`` is None
    for dense; ``bool(sparse_model)`` drives the hybrid path.
    """
    cfg = parse_embedding_config(passed) or {}
    env_sparse = SPARSE_EMBED_MODEL if USE_SPARSE_EMBEDDINGS else None
    return {
        "model": cfg.get("model") or EMBED_MODEL,
        "dim": int(cfg.get("dim") or EMBEDDING_DIM),
        "distance": cfg.get("distance") or "cosine",
        # honour an explicit sparse_model key (even null = dense); else env.
        "sparse_model": cfg["sparse_model"] if "sparse_model" in cfg else env_sparse,
    }
