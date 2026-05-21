"""File processors that convert source formats (SCORM, H5P, ...) to markdown.

To add a format, implement Processor and register it on default_registry.
"""

from __future__ import annotations

from core.processors.base import Processor
from core.processors.h5p import H5PProcessor
from core.processors.registry import ProcessorRegistry
from core.processors.scorm import ScormProcessor

default_registry = ProcessorRegistry()
default_registry.register(H5PProcessor())
default_registry.register(ScormProcessor())

__all__ = [
    "H5PProcessor",
    "Processor",
    "ProcessorRegistry",
    "ScormProcessor",
    "default_registry",
]
