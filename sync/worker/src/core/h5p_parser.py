"""H5P package parser.

.h5p files are zip archives with h5p.json (manifest) and
content/content.json (content tree). Common content types get
type-specific markdown; the rest fall through to a generic walker.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class H5PParsingError(Exception):
    """Raised when an H5P package cannot be parsed."""


class H5PManifestNotFoundError(H5PParsingError):
    """Raised when h5p.json is missing from the package."""


class H5PContentNotFoundError(H5PParsingError):
    """Raised when content/content.json is missing from the package."""


@dataclass
class H5PPackage:
    title: str
    main_library: str
    language: str
    license: str | None = None
    license_version: str | None = None
    authors: list[dict[str, str]] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    content: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    @property
    def main_library_name(self) -> str:
        """Library machine name without version (e.g. H5P.QuestionSet)."""
        return _library_name(self.main_library)


_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(value: Any) -> str:
    """Strip HTML tags and collapse whitespace. Returns "" for non-strings."""
    if not isinstance(value, str):
        return ""
    if "<" not in value and "&" not in value:
        return _WHITESPACE_RE.sub(" ", value).strip()
    text = BeautifulSoup(value, "html.parser").get_text(separator=" ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def _library_name(library: str | None) -> str:
    """ "H5P.MultiChoice 1.16" -> "H5P.MultiChoice"."""
    if not library:
        return ""
    return library.split()[0]


# UI/configuration blocks per the H5P spec, not user content
_SKIP_FIELDS = frozenset(
    {
        "behaviour",
        "UI",
        "l10n",
        "i18n",
        "overrides",
        "confirmCheck",
        "confirmRetry",
        "library",
        "subContentId",
        "metadata",
        "tipsAndFeedback",
    }
)


class H5PParser:
    """Parse .h5p packages and render them to markdown."""

    MANIFEST_NAME = "h5p.json"
    CONTENT_NAME = "content/content.json"

    def __init__(self) -> None:
        self._renderers: dict[str, Callable[[dict[str, Any], int], list[str]]] = {
            "H5P.QuestionSet": self._render_question_set,
            "H5P.MultiChoice": self._render_multi_choice,
            "H5P.Timeline": self._render_timeline,
        }

    def parse(self, path: str | Path) -> H5PPackage:
        package_path = Path(path)
        if not package_path.exists():
            raise FileNotFoundError(f"H5P package not found: {package_path}")

        try:
            with zipfile.ZipFile(package_path) as zf:
                manifest = self._read_json(zf, self.MANIFEST_NAME)
                if manifest is None:
                    raise H5PManifestNotFoundError(
                        f"Missing {self.MANIFEST_NAME} in {package_path.name}"
                    )
                content = self._read_json(zf, self.CONTENT_NAME)
                if content is None:
                    raise H5PContentNotFoundError(
                        f"Missing {self.CONTENT_NAME} in {package_path.name}"
                    )
        except zipfile.BadZipFile as exc:
            raise H5PParsingError(f"Not a valid zip archive: {package_path}") from exc

        dependencies = []
        for dep in manifest.get("preloadedDependencies") or []:
            name = dep.get("machineName")
            if not name:
                continue
            major = dep.get("majorVersion", "")
            minor = dep.get("minorVersion", "")
            dependencies.append(f"{name} {major}.{minor}".rstrip("."))

        return H5PPackage(
            title=manifest.get("title") or package_path.stem,
            main_library=manifest.get("mainLibrary", ""),
            language=manifest.get("language", "und"),
            license=manifest.get("license"),
            license_version=manifest.get("licenseVersion"),
            authors=list(manifest.get("authors") or []),
            dependencies=dependencies,
            content=content,
            source_path=package_path,
        )

    def to_markdown(self, package: H5PPackage) -> str:
        lines: list[str] = [f"# {package.title}", ""]

        if package.main_library:
            lines.append(f"**Content type:** {package.main_library}")
        if package.language and package.language != "und":
            lines.append(f"**Language:** {package.language}")
        if package.license:
            license_str = package.license
            if package.license_version:
                license_str += f" {package.license_version}"
            lines.append(f"**License:** {license_str}")
        if package.authors:
            authors = ", ".join(
                f"{a.get('name', '?')} ({a.get('role', '?')})" for a in package.authors
            )
            lines.append(f"**Authors:** {authors}")
        lines.append("")

        lines.extend(
            self._render_node(
                package.content, library=package.main_library_name, depth=2
            )
        )

        return _collapse_blank_lines(lines)

    @staticmethod
    def _read_json(zf: zipfile.ZipFile, name: str) -> dict[str, Any] | None:
        try:
            with zf.open(name) as fp:
                return json.load(fp)
        except KeyError:
            return None
        except json.JSONDecodeError as exc:
            raise H5PParsingError(f"Invalid JSON in {name}: {exc}") from exc

    def _render_node(self, node: Any, library: str, depth: int) -> list[str]:
        renderer = self._renderers.get(_library_name(library))
        if renderer is not None and isinstance(node, dict):
            return renderer(node, depth)
        return self._render_generic(node, depth)

    def _render_generic(self, node: Any, depth: int) -> list[str]:
        if node is None or isinstance(node, (int, float, bool)):
            return []
        if isinstance(node, str):
            text = strip_html(node)
            return [text, ""] if text else []
        if isinstance(node, list):
            out: list[str] = []
            for item in node:
                out.extend(self._render_generic(item, depth))
            return out
        if not isinstance(node, dict):
            return []

        # nested library invocation: dispatch on its declared type
        if "library" in node and "params" in node:
            sub_lib = _library_name(node.get("library"))
            return self._render_node(node["params"], library=sub_lib, depth=depth)

        out = []
        for key, value in node.items():
            if key in _SKIP_FIELDS:
                continue
            out.extend(self._render_generic(value, depth))
        return out

    def _render_question_set(self, node: dict[str, Any], depth: int) -> list[str]:
        out: list[str] = []

        intro = node.get("introPage") or {}
        intro_title = strip_html(intro.get("title"))
        intro_body = strip_html(intro.get("introduction"))
        if intro_title:
            out += [f"{'#' * depth} {intro_title}", ""]
        if intro_body:
            out += [intro_body, ""]

        questions = node.get("questions") or []
        if not questions:
            return out

        out += [f"{'#' * depth} Questions", ""]
        for idx, question in enumerate(questions, start=1):
            lib = _library_name(question.get("library"))
            params = question.get("params") or {}
            out += [f"{'#' * (depth + 1)} Question {idx}", ""]
            out += self._render_node(params, library=lib, depth=depth + 2)
            out.append("")
        return out

    def _render_multi_choice(self, node: dict[str, Any], depth: int) -> list[str]:
        out: list[str] = []
        question = strip_html(node.get("question"))
        if question:
            out += [question, ""]
        for answer in node.get("answers") or []:
            text = strip_html(answer.get("text"))
            if not text:
                continue
            marker = "[x]" if answer.get("correct") else "[ ]"
            out.append(f"- {marker} {text}")
        out.append("")
        return out

    def _render_timeline(self, node: dict[str, Any], depth: int) -> list[str]:
        timeline = node.get("timeline") or {}
        out: list[str] = []

        headline = strip_html(timeline.get("headline"))
        text = strip_html(timeline.get("text"))
        if headline:
            out += [f"{'#' * depth} {headline}", ""]
        if text:
            out += [text, ""]

        events = timeline.get("date") or []
        if not events:
            return out

        out += [f"{'#' * depth} Events", ""]
        for event in events:
            ev_headline = strip_html(event.get("headline"))
            ev_text = strip_html(event.get("text"))
            start = event.get("startDate") or ""
            end = event.get("endDate") or ""
            if start and end:
                date_str = f"{start} - {end}"
            else:
                date_str = start or end
            heading_parts = [p for p in (date_str, ev_headline) if p]
            if heading_parts:
                out += [f"{'#' * (depth + 1)} {' - '.join(heading_parts)}", ""]
            if ev_text:
                out += [ev_text, ""]
        return out


def _collapse_blank_lines(lines: list[str]) -> str:
    out: list[str] = []
    prev_blank = False
    for line in lines:
        blank = line.strip() == ""
        if blank and prev_blank:
            continue
        out.append(line)
        prev_blank = blank
    return "\n".join(out).rstrip() + "\n"
