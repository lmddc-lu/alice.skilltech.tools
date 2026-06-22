"""Index (vector collection) build manifest and drift detection.

Records the embedding/index configuration a Qdrant collection was built with so
config drift can be detected *before* a stale collection is queried. The three
drift types fail very differently:

- sparse on/off and embedding **dim** change are visible in Qdrant and make the
  document store raise loudly on init;
- an embedding **model** swap at the *same* dimension is invisible to Qdrant
  (it does not store the model identity) and returns silently-wrong results.

This manifest is the out-of-band source of truth that closes the silent-failure
gap. "Enable sparse" and "change the embedding model" become the same thing: the
desired manifest's fingerprint stops matching the collection's, so the
collection is flagged stale and must be rebuilt (forced reindex).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass

from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

# Fields that, if changed, invalidate existing vectors and require a rebuild
# before the collection can be queried correctly. Chunker fields are recorded in
# the manifest for debugging but are quality-only (they do not break queries);
# bump INDEX_SCHEMA_VERSION to force a rebuild when only chunking changes.
_FINGERPRINT_FIELDS = (
    "schema_version",
    "embedding_model",
    "embedding_dim",
    "distance",
    "sparse_model",
)


@dataclass(frozen=True)
class IndexManifest:
    """How a Qdrant collection was built."""

    schema_version: int
    embedding_model: str
    embedding_dim: int
    distance: str
    sparse_model: str | None
    chunker_tokenizer: str
    chunker_max_tokens: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    def to_wire(self) -> dict:
        """The embedding identity to push to the rag-pipeline (no secrets/endpoint).

        The pipeline builds/queries with exactly these fields, so they must
        describe the collection this manifest belongs to.
        """
        return {
            "model": self.embedding_model,
            "dim": self.embedding_dim,
            "distance": self.distance,
            "sparse_model": self.sparse_model,
        }

    @classmethod
    def from_json(cls, raw: str) -> IndexManifest:
        data = json.loads(raw)
        return cls(
            schema_version=int(data["schema_version"]),
            embedding_model=str(data["embedding_model"]),
            embedding_dim=int(data["embedding_dim"]),
            distance=str(data["distance"]),
            sparse_model=data.get("sparse_model"),
            chunker_tokenizer=str(data.get("chunker_tokenizer", "")),
            chunker_max_tokens=int(data.get("chunker_max_tokens", 0)),
        )

    @property
    def kind(self) -> str:
        """Retrieval kind this manifest describes: ``hybrid`` if it carries a
        sparse model, else ``dense``."""
        return "hybrid" if self.sparse_model else "dense"

    @property
    def fingerprint(self) -> str:
        """Stable hash of the query-affecting subset.

        Two collections with the same fingerprint can serve each other's
        queries; a different fingerprint means a rebuild is required.
        """
        subset = {field: getattr(self, field) for field in _FINGERPRINT_FIELDS}
        blob = json.dumps(subset, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def desired_manifest() -> IndexManifest:
    """The manifest the system currently wants every collection built with."""
    return IndexManifest(
        schema_version=settings.INDEX_SCHEMA_VERSION,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_dim=settings.EMBEDDING_DIM,
        distance=settings.EMBEDDING_DISTANCE,
        sparse_model=settings.SPARSE_EMBEDDING_MODEL or None,
        chunker_tokenizer=settings.CHUNKER_TOKENIZER,
        chunker_max_tokens=settings.CHUNKER_MAX_TOKENS,
    )


def wire_embedding_config() -> dict:
    """The *desired* embedding config: what a (re)built collection should use.

    This is the push half of the single-source-of-truth design: the API
    dictates the embedding identity (not secrets/endpoint, those stay in the
    pipeline's env) so the pipeline builds with exactly what ``desired_manifest``
    records. Use it for a forced reindex; for queries and incremental adds use
    ``wire_config_for_manifest`` so an existing collection keeps being served
    with the model it was actually built with (progressive migration).
    """
    return desired_manifest().to_wire()


def _parse_manifest_or_none(stored_manifest_json: str | None) -> IndexManifest | None:
    """Parse a stored manifest, or return None if it is absent or unparseable.

    Centralises the "a missing or bad manifest must never wedge chat" guard:
    callers fall back to the desired config / treat the KB as non-stale. NULL is
    expected (brand-new or pre-tracking KB) and silent; an unparseable row is
    logged so a corrupt manifest is visible without breaking queries.
    """
    if not stored_manifest_json:
        return None
    try:
        return IndexManifest.from_json(stored_manifest_json)
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("Unparseable index_manifest, falling back to desired: %s", e)
        return None


def wire_config_for_manifest(stored_manifest_json: str | None) -> dict:
    """The embedding config to query/incrementally-ingest an existing collection.

    A collection must be served with the embedding model it was built with, not
    the current desired one otherwise a model swap returns silently-wrong
    results until the collection is reindexed. The stored manifest is that
    record (Qdrant cannot report the model itself). This lets old and new models
    coexist: each KB stays on its own model until a forced reindex migrates it.

    Falls back to the desired config when no manifest is recorded yet (NULL: a
    brand-new KB, or one built before manifest tracking) or it is unparseable,
    so behaviour matches the pre-progressive default in those cases.
    """
    stored = _parse_manifest_or_none(stored_manifest_json)
    return stored.to_wire() if stored else wire_embedding_config()


@dataclass(frozen=True)
class DriftResult:
    stale: bool
    reason: str | None = None


def evaluate_drift(stored_manifest_json: str | None) -> DriftResult:
    """Compare a collection's stored manifest against the desired config.

    A missing manifest (NULL) is treated as NOT stale: existing collections are
    backfilled to the current manifest by migration, and a brand-new KB has no
    collection to be stale against yet. Only an explicitly-recorded, differing
    fingerprint counts as drift. An unparseable manifest is likewise treated as
    non-stale so a bad row can never wedge chat.
    """
    desired = desired_manifest()
    stored = _parse_manifest_or_none(stored_manifest_json)
    if stored is None or stored.fingerprint == desired.fingerprint:
        return DriftResult(stale=False)

    reason = (
        f"built with {stored.embedding_model}/dim={stored.embedding_dim}/"
        f"sparse={stored.sparse_model} (v{stored.schema_version}); "
        f"desired {desired.embedding_model}/dim={desired.embedding_dim}/"
        f"sparse={desired.sparse_model} (v{desired.schema_version})"
    )
    return DriftResult(stale=True, reason=reason)


def enforce_index_freshness(kb) -> None:
    """Apply the configured drift policy to a KB about to be queried.

    Policy is ``settings.INDEX_DRIFT_ENFORCEMENT``:

    - ``off``: do nothing;
    - ``warn``: log a warning if stale, still serve (default; dormant while the
      desired config equals what collections were built with);
    - ``block``: reject a stale KB with 409 so a drifted collection is never
      queried (turn this on once the backfill/reindex story is wired).

    Raises ``HTTPException(409)`` only under ``block``.
    """
    policy = settings.INDEX_DRIFT_ENFORCEMENT
    if policy == "off":
        return

    drift = evaluate_drift(getattr(kb, "index_manifest", None))
    if not drift.stale:
        return

    logger.warning("Index drift for KB %s: %s", getattr(kb, "id", "?"), drift.reason)
    if policy == "block":
        raise HTTPException(
            status_code=409,
            detail=(
                "This chatbot's knowledge base needs reindexing after a "
                "configuration change. Please reindex before chatting."
            ),
        )
