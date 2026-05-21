"""H5P package processor."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from core.h5p_parser import H5PParser

logger = logging.getLogger(__name__)


class H5PProcessor:
    """Convert an H5P package to markdown.

    Matches .h5p or any zip with h5p.json at the root.
    """

    name = "h5p"

    MANIFEST_NAME = "h5p.json"

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() == ".h5p":
            return True
        if path.suffix.lower() != ".zip":
            return False
        try:
            if not zipfile.is_zipfile(path):
                return False
            with zipfile.ZipFile(path) as zf:
                return self.MANIFEST_NAME in zf.namelist()
        except (zipfile.BadZipFile, OSError):
            return False

    def process(self, path: Path, temp_dir: Path) -> Path:
        parser = H5PParser()
        package = parser.parse(path)
        markdown_path = temp_dir / (path.stem + ".md")
        markdown_path.write_text(parser.to_markdown(package), encoding="utf-8")
        logger.info(
            "Processed H5P: %s -> %s (type=%s)",
            path.name,
            markdown_path.name,
            package.main_library_name,
        )
        return markdown_path
