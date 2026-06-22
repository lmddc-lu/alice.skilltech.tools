"""Per-collection sparse resolution logic.

Only the pure decision logic is exercised; the Qdrant inspection in
``collection_has_sparse`` is monkeypatched, so no qdrant install/connection is
needed (its heavy imports are deferred inside the module).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def index_config():
    import index_config as module

    return module


class TestResolveSparseForIndex:
    def test_recreate_uses_desired_default(self, index_config, monkeypatch) -> None:
        # a forced reindex builds with the desired default — this is how a
        # collection migrates to a new config.
        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", True)
        assert index_config.resolve_sparse_for_index("kb", recreate=True) is True
        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", False)
        assert index_config.resolve_sparse_for_index("kb", recreate=True) is False

    def test_existing_collection_matches_detection(
        self, index_config, monkeypatch
    ) -> None:
        # detection wins over the default so the store never mismatches.
        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", False)
        monkeypatch.setattr(index_config, "collection_has_sparse", lambda _: True)
        assert index_config.resolve_sparse_for_index("kb") is True

        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", True)
        monkeypatch.setattr(index_config, "collection_has_sparse", lambda _: False)
        assert index_config.resolve_sparse_for_index("kb") is False

    def test_missing_collection_uses_desired_default(
        self, index_config, monkeypatch
    ) -> None:
        monkeypatch.setattr(index_config, "collection_has_sparse", lambda _: None)
        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", True)
        assert index_config.resolve_sparse_for_index("kb") is True
        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", False)
        assert index_config.resolve_sparse_for_index("kb") is False

    def test_desired_sparse_override_wins_on_recreate(
        self, index_config, monkeypatch
    ) -> None:
        # API-dictated config overrides the env default on a (re)build.
        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", False)
        assert (
            index_config.resolve_sparse_for_index(
                "kb", recreate=True, desired_sparse=True
            )
            is True
        )

    def test_existing_collection_ignores_desired_override(
        self, index_config, monkeypatch
    ) -> None:
        # even if the API wants sparse, an existing dense collection stays dense
        # (it must be reindexed to migrate) so the store never mismatches.
        monkeypatch.setattr(index_config, "collection_has_sparse", lambda _: False)
        assert index_config.resolve_sparse_for_index("kb", desired_sparse=True) is False


class TestResolveEmbeddingConfig:
    def test_none_falls_back_to_env(self, index_config, monkeypatch) -> None:
        monkeypatch.setattr(index_config, "EMBED_MODEL", "env-model")
        monkeypatch.setattr(index_config, "EMBEDDING_DIM", 1234)
        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", False)
        cfg = index_config.resolve_embedding_config(None)
        assert cfg == {
            "model": "env-model",
            "dim": 1234,
            "distance": "cosine",
            "sparse_model": None,
        }

    def test_env_sparse_default_used_when_absent(
        self, index_config, monkeypatch
    ) -> None:
        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", True)
        monkeypatch.setattr(index_config, "SPARSE_EMBED_MODEL", "splade")
        assert index_config.resolve_embedding_config(None)["sparse_model"] == "splade"

    def test_passed_config_overrides_env(self, index_config, monkeypatch) -> None:
        monkeypatch.setattr(index_config, "EMBED_MODEL", "env-model")
        cfg = index_config.resolve_embedding_config(
            {"model": "api-model", "dim": 2560, "sparse_model": "sp"}
        )
        assert cfg["model"] == "api-model"
        assert cfg["dim"] == 2560
        assert cfg["sparse_model"] == "sp"

    def test_explicit_null_sparse_means_dense(self, index_config, monkeypatch) -> None:
        # an explicit null sparse_model forces dense even if env wants sparse.
        monkeypatch.setattr(index_config, "USE_SPARSE_EMBEDDINGS", True)
        monkeypatch.setattr(index_config, "SPARSE_EMBED_MODEL", "splade")
        cfg = index_config.resolve_embedding_config({"sparse_model": None})
        assert cfg["sparse_model"] is None

    def test_accepts_json_string(self, index_config) -> None:
        cfg = index_config.resolve_embedding_config('{"model": "m", "dim": 8}')
        assert cfg["model"] == "m"
        assert cfg["dim"] == 8

    def test_unparseable_string_falls_back(self, index_config, monkeypatch) -> None:
        monkeypatch.setattr(index_config, "EMBED_MODEL", "env-model")
        assert index_config.resolve_embedding_config("not json")["model"] == "env-model"
