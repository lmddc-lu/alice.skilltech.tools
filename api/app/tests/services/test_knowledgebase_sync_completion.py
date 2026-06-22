"""Index-manifest stamping on KB sync completion."""

import dataclasses

from sqlmodel import Session

from app.models.tables import KnowledgeBase, User
from app.services import index_manifest as im
from app.services.knowledgebase_service import KnowledgebaseService


def _make_kb(db: Session, user: User, manifest: str | None) -> KnowledgeBase:
    kb = KnowledgeBase(name="kb", user_id=user.id, index_manifest=manifest)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


def _completion(kb_id, *, force: bool) -> dict:
    return {
        "knowledge_base_id": str(kb_id),
        "files_processed": 1,
        "files_succeeded": 1,
        "files_failed": 0,
        "force": force,
    }


def _stale_manifest() -> str:
    return dataclasses.replace(
        im.desired_manifest(), embedding_model="old-model"
    ).to_json()


def _reload(db: Session, kb_id) -> KnowledgeBase:
    db.expire_all()
    return db.get(KnowledgeBase, kb_id)


class TestSyncCompletionStamping:
    def test_new_kb_null_manifest_gets_stamped(
        self, db: Session, test_user: User
    ) -> None:
        kb = _make_kb(db, test_user, manifest=None)

        KnowledgebaseService(db).handle_knowledgebase_sync_completion(
            _completion(kb.id, force=False)
        )

        # brand-new collection built fresh under current config → stamp desired
        assert _reload(db, kb.id).index_manifest == im.desired_manifest().to_json()

    def test_forced_reindex_restamps_stale_manifest(
        self, db: Session, test_user: User
    ) -> None:
        kb = _make_kb(db, test_user, manifest=_stale_manifest())

        KnowledgebaseService(db).handle_knowledgebase_sync_completion(
            _completion(kb.id, force=True)
        )

        # recreate under current config → manifest advances to desired
        assert _reload(db, kb.id).index_manifest == im.desired_manifest().to_json()

    def test_incremental_add_does_not_mask_drift(
        self, db: Session, test_user: User
    ) -> None:
        stale = _stale_manifest()
        kb = _make_kb(db, test_user, manifest=stale)

        KnowledgebaseService(db).handle_knowledgebase_sync_completion(
            _completion(kb.id, force=False)
        )

        # non-forced add to an already-stamped collection must NOT overwrite a
        # stale manifest the collection really is still on the old config.
        reloaded = _reload(db, kb.id)
        assert reloaded.index_manifest == stale
        assert im.evaluate_drift(reloaded.index_manifest).stale is True

    def test_completion_sets_status_ready(self, db: Session, test_user: User) -> None:
        kb = _make_kb(db, test_user, manifest=None)

        KnowledgebaseService(db).handle_knowledgebase_sync_completion(
            _completion(kb.id, force=False)
        )

        assert _reload(db, kb.id).status == "ready"
