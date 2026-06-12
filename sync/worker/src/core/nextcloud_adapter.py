"""NextCloud source adapter (stub).

All operations are unimplemented; sync_metadata and sync_content return
empty results so a NextCloud datasource doesn't break a multi-source job.
"""

from __future__ import annotations

import logging

from core.source_adapter import SourceAdapter
from core.source_types import SourceType

logger = logging.getLogger(__name__)


class NextCloudSourceAdapter(SourceAdapter):
    source_type = SourceType.NEXTCLOUD

    def __init__(self, config, storage):
        self.config = config
        self.storage = storage

    def sync_metadata(self, message: dict, force: bool) -> list[dict]:
        logger.info("NextCloud metadata sync not yet implemented")
        return []

    def sync_content(self, message: dict, selected_files: list, force: bool) -> int:
        logger.info("NextCloud content sync not yet implemented")
        return 0

    def ensure_content(
        self,
        datasource: dict,
        owner_email: str,
        selected_files: list,
        force: bool,
    ) -> tuple[int, list[str]]:
        logger.warning("NextCloud auto-download not yet implemented")
        return 0, []
