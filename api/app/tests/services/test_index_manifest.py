"""Index manifest fingerprinting and drift detection."""

import dataclasses

import pytest
from fastapi import HTTPException

from app.services import index_manifest as im


def _manifest(**overrides) -> im.IndexManifest:
    base = im.desired_manifest()
    return dataclasses.replace(base, **overrides)


class TestFingerprint:
    def test_stable_for_same_config(self) -> None:
        assert _manifest().fingerprint == _manifest().fingerprint

    def test_survives_json_roundtrip(self) -> None:
        m = _manifest()
        assert im.IndexManifest.from_json(m.to_json()).fingerprint == m.fingerprint

    @pytest.mark.parametrize(
        "overrides",
        [
            {"embedding_model": "some-other-model"},
            {"embedding_dim": 1024},
            {"distance": "dot"},
            {"sparse_model": "prithvida/Splade_PP_en_v1"},
            {"schema_version": 99},
        ],
    )
    def test_query_breaking_changes_change_fingerprint(self, overrides) -> None:
        assert _manifest(**overrides).fingerprint != _manifest().fingerprint

    @pytest.mark.parametrize(
        "overrides",
        [
            {"chunker_tokenizer": "bert-base-uncased"},
            {"chunker_max_tokens": 256},
        ],
    )
    def test_quality_only_changes_do_not_change_fingerprint(self, overrides) -> None:
        # chunker drift is recorded but must not, by itself, flag a collection
        # stale; bump INDEX_SCHEMA_VERSION for that.
        assert _manifest(**overrides).fingerprint == _manifest().fingerprint


class TestWireEmbeddingConfig:
    def test_matches_desired_manifest_fields(self) -> None:
        # the pushed config must describe exactly what the manifest records, so
        # build/query/manifest stay in lockstep.
        m = im.desired_manifest()
        wire = im.wire_embedding_config()
        assert wire == {
            "model": m.embedding_model,
            "dim": m.embedding_dim,
            "distance": m.distance,
            "sparse_model": m.sparse_model,
        }

    def test_carries_no_secrets(self) -> None:
        # identity only; endpoint/keys stay in the pipeline's env.
        assert set(im.wire_embedding_config()) == {
            "model",
            "dim",
            "distance",
            "sparse_model",
        }


class TestWireConfigForManifest:
    def test_stale_kb_is_served_with_its_own_model(self) -> None:
        # progressive migration: a KB built on the old model must be queried
        # with that model, NOT the current desired one, until it is reindexed.
        stored = _manifest(embedding_model="old-model", embedding_dim=1024).to_json()
        wire = im.wire_config_for_manifest(stored)
        assert wire["model"] == "old-model"
        assert wire["dim"] == 1024
        assert wire["model"] != im.desired_manifest().embedding_model

    def test_null_manifest_falls_back_to_desired(self) -> None:
        # a brand-new / pre-tracking KB has no recorded model: use desired.
        assert im.wire_config_for_manifest(None) == im.wire_embedding_config()
        assert im.wire_config_for_manifest("") == im.wire_embedding_config()

    def test_unparseable_manifest_falls_back_to_desired(self) -> None:
        assert im.wire_config_for_manifest("not json") == im.wire_embedding_config()


class TestEvaluateDrift:
    def test_null_manifest_is_not_stale(self) -> None:
        # existing rows are backfilled by migration; a brand-new KB has no
        # collection to be stale against yet.
        assert im.evaluate_drift(None).stale is False
        assert im.evaluate_drift("").stale is False

    def test_unparseable_manifest_is_not_stale(self) -> None:
        assert im.evaluate_drift("not json").stale is False
        assert im.evaluate_drift('{"embedding_model": "x"}').stale is False

    def test_matching_manifest_is_not_stale(self) -> None:
        assert im.evaluate_drift(im.desired_manifest().to_json()).stale is False

    def test_model_swap_is_stale(self) -> None:
        stored = _manifest(embedding_model="old-model").to_json()
        result = im.evaluate_drift(stored)
        assert result.stale is True
        assert "old-model" in result.reason

    def test_sparse_toggle_is_stale(self) -> None:
        stored = _manifest(sparse_model="prithvida/Splade_PP_en_v1").to_json()
        assert im.evaluate_drift(stored).stale is True


class TestEnforceIndexFreshness:
    class _KB:
        id = "kb-1"

        def __init__(self, manifest: str | None) -> None:
            self.index_manifest = manifest

    def test_off_never_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(im.settings, "INDEX_DRIFT_ENFORCEMENT", "off")
        stale = self._KB(_manifest(embedding_model="old").to_json())
        im.enforce_index_freshness(stale)  # no raise

    def test_warn_logs_but_serves(self, monkeypatch) -> None:
        monkeypatch.setattr(im.settings, "INDEX_DRIFT_ENFORCEMENT", "warn")
        stale = self._KB(_manifest(embedding_model="old").to_json())
        im.enforce_index_freshness(stale)  # no raise

    def test_block_rejects_stale(self, monkeypatch) -> None:
        monkeypatch.setattr(im.settings, "INDEX_DRIFT_ENFORCEMENT", "block")
        stale = self._KB(_manifest(embedding_model="old").to_json())
        with pytest.raises(HTTPException) as exc:
            im.enforce_index_freshness(stale)
        assert exc.value.status_code == 409

    def test_block_serves_fresh(self, monkeypatch) -> None:
        monkeypatch.setattr(im.settings, "INDEX_DRIFT_ENFORCEMENT", "block")
        fresh = self._KB(im.desired_manifest().to_json())
        im.enforce_index_freshness(fresh)  # no raise
