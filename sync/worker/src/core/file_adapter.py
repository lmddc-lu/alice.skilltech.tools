"""FILE source adapter.

Files arrive in MinIO via the API's direct upload path, so only
ensure_content and collect_files are implemented. sync_metadata and
sync_content inherit the base's ValueError.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.source_adapter import SourceAdapter
from core.source_types import SourceType
from storage.minio_client import object_etag

logger = logging.getLogger(__name__)


class FileSourceAdapter(SourceAdapter):
    source_type = SourceType.FILE

    def __init__(self, config, storage):
        self.config = config
        self.storage = storage

    def ensure_content(
        self,
        datasource: dict,
        owner_email: str,
        selected_files: list,
        force: bool,
    ) -> tuple[int, list[str]]:
        """Verify each selected file is present in storage.

        Always returns (0, []), nothing is downloaded or pruned. Missing
        files are logged so a broken upload surfaces here instead of later as
        a confusing ingestion failure.
        """
        datasource_id = datasource.get("datasource_id")
        logger.info(f"FILE datasource {datasource_id}: Verifying files")
        verified_count = 0
        for file_entry in selected_files:
            file_path = (
                file_entry["path"] if isinstance(file_entry, dict) else file_entry
            )
            try:
                if self._file_exists(file_path):
                    verified_count += 1
                    logger.debug(f"Verified file exists: {file_path}")
                else:
                    logger.warning(f"File not found in storage: {file_path}")
            except Exception as e:
                logger.error(f"Error verifying file {file_path}: {e}")
        logger.info(
            f"Verified {verified_count}/{len(selected_files)} files for FILE datasource"
        )
        return 0, []

    def collect_files(self, datasource: dict, owner_email: str) -> list[dict]:
        """Turn the selection list into ingestion entries.

        Accepts dict entries (file_id / filename / mime_type) or plain string
        paths; the two upload paths produce different shapes.
        """
        datasource_id = datasource.get("datasource_id")
        selected_files = datasource.get("selected_files", [])
        logger.info(f"Processing FILE datasource {datasource_id}")
        objects: list[dict] = []
        for file_entry in selected_files:
            if isinstance(file_entry, dict):
                file_path = file_entry["path"]
                file_id = file_entry.get("file_id")
                filename = file_entry.get("filename", Path(file_path).name)
                mime_type = file_entry.get("mime_type")
            else:
                file_path = file_entry
                file_id = None
                filename = Path(file_path).name
                mime_type = None
            try:
                stat = self._stat_object(file_path)
                if stat is not None:
                    objects.append(
                        {
                            "path": Path(file_path),
                            "file_id": file_id,
                            "filename": filename,
                            "mime_type": mime_type,
                            "content_etag": object_etag(stat),
                        }
                    )
                    logger.info(f"Added FILE datasource file: {file_path}")
                else:
                    logger.warning(f"File not found: {file_path}")
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {e}")
        return objects

    def _file_exists(self, file_path: str) -> bool:
        return self._stat_object(file_path) is not None

    def _stat_object(self, file_path: str):
        """Stat of the storage object, or None when it does not exist."""
        try:
            return self.storage.client.stat_object(
                bucket_name=self.config.bucket_name, object_name=file_path
            )
        except Exception as e:
            logger.debug(f"File does not exist: {file_path} - Error: {e}")
            return None
