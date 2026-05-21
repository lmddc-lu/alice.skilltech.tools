"""SCORM package processor."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from core.scorm_parser import ScormParser

logger = logging.getLogger(__name__)


class ScormProcessor:
    """Convert a SCORM package (.zip containing imsmanifest.xml) to markdown."""

    name = "scorm"

    # SCORM 1.2 / 2004 mandate the manifest at the package root.
    MANIFEST_NAME = "imsmanifest.xml"

    def can_handle(self, path: Path) -> bool:
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
        markdown_path = temp_dir / (path.stem + ".md")
        with ScormParser() as parser:
            package = parser.parse_package(str(path))
            content_list = parser.extract_all_content(package)
            markdown_path.write_text(
                _render_markdown(package, content_list), encoding="utf-8"
            )
        logger.info("Processed SCORM: %s -> %s", path.name, markdown_path.name)
        return markdown_path


def _render_markdown(package, content_list: list[dict]) -> str:
    parts: list[str] = [
        f"# {package.title}\n\n",
        f"**SCORM Version:** {package.version}\n",
        f"**Package ID:** {package.identifier}\n\n",
    ]
    if package.description:
        parts.append(f"## Description\n\n{package.description}\n\n")
    parts.append("## Content\n\n")
    for content in content_list:
        if content.get("type") == "rise_articulate":
            parts.append("### Rise Articulate Course\n\n")
            if content.get("total_text"):
                parts.append(content["total_text"])
        else:
            if content.get("title"):
                parts.append(f"### {content['title']}\n\n")
            if content.get("total_text"):
                parts.append(content["total_text"])
                parts.append("\n\n")
    return "".join(parts)
