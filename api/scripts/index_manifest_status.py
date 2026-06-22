"""Report each knowledge base's index manifest vs the current desired config.

Read-only. Use during a progressive embedding rollout (e.g. enabling
sparse/hybrid) to track which KBs are already on the target config and which
still need a reindex.

Each KB falls in one bucket:
    current  - stored manifest matches the desired config (migrated; the state
               INDEX_DRIFT_ENFORCEMENT=block allows through)
    pending  - stored manifest differs from desired (drifted -> needs a reindex;
               this is what `block` would reject)
    unknown  - no manifest yet (NULL: built before tracking, or not stamped).
               `block` does NOT reject these, but they aren't confirmed migrated.

"kind" is what the stored manifest says the collection is: dense / hybrid /
unknown. It is safe to set INDEX_DRIFT_ENFORCEMENT=block once `pending` is 0
(ideally `unknown` too, so every KB is confirmed on the target config).

Usage (from the api/ directory or inside the api container):
    python scripts/index_manifest_status.py            # summary
    python scripts/index_manifest_status.py --verbose  # one line per KB
"""

import logging
import sys

from sqlmodel import Session, select

from app.core.db import engine
from app.models.tables import KnowledgeBase
from app.services.index_manifest import (
    IndexManifest,
    desired_manifest,
    evaluate_drift,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _stored_kind(manifest_json: str | None) -> str:
    """dense / hybrid from a stored manifest, or unknown if absent/unparseable."""
    if not manifest_json:
        return "unknown"
    try:
        manifest = IndexManifest.from_json(manifest_json)
    except (ValueError, KeyError, TypeError):
        return "unknown"
    return manifest.kind


def rollout_status(session: Session) -> dict:
    """Classify every KB against the desired config. Returns a report dict.

    Keys: ``desired_kind``, ``desired_fingerprint``, ``counts`` (current /
    pending / unknown), and ``rows`` (id, name, kind, bucket per KB).
    """
    desired = desired_manifest()
    counts = {"current": 0, "pending": 0, "unknown": 0}
    rows = []
    for kb in session.exec(select(KnowledgeBase)).all():
        manifest = kb.index_manifest
        if manifest is None:
            bucket = "unknown"
        else:
            bucket = "pending" if evaluate_drift(manifest).stale else "current"
        counts[bucket] += 1
        rows.append(
            {
                "id": str(kb.id),
                "name": kb.name,
                "kind": _stored_kind(manifest),
                "bucket": bucket,
            }
        )
    return {
        "desired_kind": desired.kind,
        "desired_fingerprint": desired.fingerprint,
        "counts": counts,
        "rows": rows,
    }


def main() -> None:
    verbose = any(a in ("-v", "--verbose") for a in sys.argv[1:])
    with Session(engine) as session:
        report = rollout_status(session)

    if verbose:
        for row in sorted(report["rows"], key=lambda r: r["bucket"]):
            logger.info(
                "  %-8s %-8s %s  %s",
                row["bucket"],
                row["kind"],
                row["id"],
                row["name"],
            )

    c = report["counts"]
    total = sum(c.values())
    logger.info(
        "desired=%s (fp=%s) | total=%d  current=%d  pending=%d  unknown=%d",
        report["desired_kind"],
        report["desired_fingerprint"],
        total,
        c["current"],
        c["pending"],
        c["unknown"],
    )
    if c["pending"] == 0 and c["unknown"] == 0:
        logger.info(
            "All KBs on desired config -> safe to set INDEX_DRIFT_ENFORCEMENT=block."
        )
    elif c["pending"] == 0:
        logger.info(
            "No drifted KBs; %d unknown (NULL) remain -> `block` won't reject "
            "them, but they aren't confirmed migrated.",
            c["unknown"],
        )
    else:
        logger.info(
            "%d KB(s) still need a reindex before enabling `block`.", c["pending"]
        )


if __name__ == "__main__":
    main()
