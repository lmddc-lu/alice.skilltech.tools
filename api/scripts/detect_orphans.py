"""CLI entry point for orphan detection.

Usage:
    uv run python -m scripts.detect_orphans            # text summary
    uv run python -m scripts.detect_orphans --json     # JSON to stdout
    uv run python -m scripts.detect_orphans --skip-s3  # DB-only

Read-only. Never mutates DB or bucket. Non-zero exit only on bad
invocation; not a health check.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from sqlmodel import Session

from app.core.db import engine
from app.core.storage import StorageManager
from app.services.orphan_detection import OrphanReport, detect_all


def _print_text(reports: list[OrphanReport]) -> None:
    total = sum(r.count for r in reports)
    print(f"Orphan detection: {total} orphan(s) across {len(reports)} categor(ies)\n")
    for r in reports:
        marker = "  " if r.is_empty() else "!!"
        print(f"{marker} {r.category}: {r.count}")
        print(f"     {r.description}")
        if r.sample_ids:
            preview = ", ".join(r.sample_ids[:5])
            more = "" if r.count <= 5 else f" (+{r.count - 5} more, up to 100 stored)"
            print(f"     samples: {preview}{more}")
        print()


def _print_json(reports: list[OrphanReport]) -> None:
    payload = [dataclasses.asdict(r) for r in reports]
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect orphaned data (read-only).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument(
        "--skip-s3",
        action="store_true",
        help="Skip S3 orphan detection (run DB checks only)",
    )
    args = parser.parse_args()

    storage = None if args.skip_s3 else StorageManager()
    with Session(engine) as session:
        reports = detect_all(session, storage)

    if args.json:
        _print_json(reports)
    else:
        _print_text(reports)


if __name__ == "__main__":
    main()
