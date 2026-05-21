"""Registry that picks the right Processor for a given file."""

from __future__ import annotations

import logging
from pathlib import Path

from core.processors.base import Processor

logger = logging.getLogger(__name__)


class ProcessorRegistry:
    """Ordered list of processors; first matching can_handle wins.

    A processor that raises from can_handle is skipped and logged so one
    broken processor can't break dispatch.
    """

    def __init__(self) -> None:
        self._processors: list[Processor] = []

    def register(self, processor: Processor) -> None:
        self._processors.append(processor)

    def find(self, path: Path) -> Processor | None:
        for processor in self._processors:
            try:
                if processor.can_handle(path):
                    return processor
            except Exception:
                logger.warning(
                    "Processor %s.can_handle failed for %s",
                    processor.name,
                    path.name,
                    exc_info=True,
                )
        return None

    def __len__(self) -> int:
        return len(self._processors)
