"""One-off: stamp every knowledge base's index_manifest with the current config.

Use this when the embedding config in the environment has changed *in label only*
but the existing Qdrant collections already match it

WARNING: this asserts that *every* collection matches the current desired config
(app.services.index_manifest.desired_manifest)

Usage (from the api/ directory or inside the api container):
    python app/stamp_index_manifests.py             # apply
    python app/stamp_index_manifests.py --dry-run   # report only, no writes
"""

import logging
import sys

from sqlmodel import Session, select

from app.core.db import engine
from app.models.tables import KnowledgeBase
from app.services.index_manifest import desired_manifest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def stamp_all(session: Session, dry_run: bool = False) -> tuple[int, int]:
    """Stamp every KB's index_manifest with the current desired config.

    Returns ``(updated, already_current)``. Rows already carrying the current
    manifest are left untouched.
    """
    desired = desired_manifest()
    manifest_json = desired.to_json()

    kbs = session.exec(select(KnowledgeBase)).all()
    updated = 0
    already_current = 0
    for kb in kbs:
        if kb.index_manifest == manifest_json:
            already_current += 1
            continue
        logger.info(
            "KB %s: %s -> current",
            kb.id,
            "NULL" if kb.index_manifest is None else "relabel/stale",
        )
        if not dry_run:
            kb.index_manifest = manifest_json
        updated += 1

    if not dry_run and updated:
        session.commit()
    return updated, already_current


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    with Session(engine) as session:
        updated, already_current = stamp_all(session, dry_run=dry_run)
    logger.info(
        "%s %d knowledge base(s); %d already current. fingerprint=%s",
        "Would stamp" if dry_run else "Stamped",
        updated,
        already_current,
        desired_manifest().fingerprint,
    )


if __name__ == "__main__":
    main()
