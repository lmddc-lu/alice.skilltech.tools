"""Processor protocol: convert source files to markdown for RAG ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Processor(Protocol):
    """Convert a source file (SCORM, H5P, ...) into a markdown document.

    Implementations are stateless and registered with ProcessorRegistry.
    can_handle should peek inside the file rather than rely on filename
    heuristics.
    """

    name: str

    def can_handle(self, path: Path) -> bool:
        """True if this processor recognizes the file.

        Must be cheap, side-effect-free, and never raise; return False on
        any inspection error.
        """
        ...

    def process(self, path: Path, temp_dir: Path) -> Path:
        """Convert path to markdown under temp_dir and return its path."""
        ...
