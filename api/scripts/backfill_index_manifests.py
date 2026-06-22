"""One-off: backfill index_manifest for collections built BEFORE a config change.

Use this once, right after enabling a new embedding setting (here: turning
sparse/hybrid retrieval ON) on a deployment whose existing collections were all
built under the PREVIOUS config.

This script instead stamps each *untracked* KB (``index_manifest IS NULL``) with
the manifest it was actually built with: the desired config with the changed
fields overridden back to their pre-change values (here ``sparse_model=None``,
i.e. dense). KBs that already carry a manifest are left untouched — they were
built/stamped under the current regime and their manifest is authoritative
(e.g. a KB re-synced after the sparse rollout self-stamped the desired config).

Pre-requisite: every NULL-manifest collection really was built under the
overridden ("as-built") config. That holds when the setting was globally OFF
before and nothing has been reindexed since enabling it. If the corpus is mixed,
this assumption is wrong — inspect Qdrant per collection instead.

After running, ``index_manifest_status.py`` correctly reports these KBs as
``pending`` (drifted -> need a forced reindex to migrate). Reindex them at your
pace; each forced reindex rebuilds under the desired config and restamps.

Usage (from the api/ directory or inside the api container):
    python scripts/backfill_index_manifests.py             # apply
    python scripts/backfill_index_manifests.py --dry-run   # report only, no writes
"""

import dataclasses
import logging
import sys

from sqlmodel import Session, select

from app.core.db import engine
from app.models.tables import KnowledgeBase
from app.services.index_manifest import desired_manifest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def as_built_manifest() -> str:
    """The manifest the untracked collections were actually built with.

    The desired config with the fields that changed at the rollout overridden
    back to their previous values. Here only sparse was toggled on, so the
    as-built config is dense (``sparse_model=None``); the embedding model/dim are
    unchanged, so they carry over from the desired config.
    """
    return dataclasses.replace(desired_manifest(), sparse_model=None).to_json()


def backfill_untracked(session: Session, dry_run: bool = False) -> tuple[int, int]:
    """Stamp every NULL-manifest KB with the as-built (pre-change) manifest.

    Returns ``(stamped, skipped)``. Rows that already carry a manifest are
    skipped: they were stamped under the current regime and are authoritative.
    """
    manifest_json = as_built_manifest()

    kbs = session.exec(select(KnowledgeBase)).all()
    stamped = 0
    skipped = 0
    for kb in kbs:
        if kb.index_manifest is not None:
            skipped += 1
            continue
        logger.info("KB %s: NULL -> as-built (dense)", kb.id)
        if not dry_run:
            kb.index_manifest = manifest_json
        stamped += 1

    if not dry_run and stamped:
        session.commit()
    return stamped, skipped


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    with Session(engine) as session:
        stamped, skipped = backfill_untracked(session, dry_run=dry_run)
    logger.info(
        "%s %d untracked KB(s) as-built; %d already tracked (left as-is). "
        "as-built fingerprint=%s, desired fingerprint=%s",
        "Would stamp" if dry_run else "Stamped",
        stamped,
        skipped,
        dataclasses.replace(desired_manifest(), sparse_model=None).fingerprint,
        desired_manifest().fingerprint,
    )


if __name__ == "__main__":
    main()
