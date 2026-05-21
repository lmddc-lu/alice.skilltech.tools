"""Source adapter base class.

A SourceAdapter is the strategy for one SourceType. The worker keeps a
{SourceType: SourceAdapter} registry and dispatches each pipeline through it.

sync_metadata / sync_content raise on unsupported types so misconfigured
datasources fail loudly. ensure_content and collect_files default to no-ops
for types with no work in those phases.
"""

from __future__ import annotations

from core.source_types import SourceType


class SourceAdapter:
    """Strategy contract for one source type. Subclasses set `source_type`."""

    source_type: SourceType

    def sync_metadata(self, message: dict, force: bool) -> list[dict]:
        raise ValueError(
            f"Metadata sync not supported for source_type {self.source_type.name}"
        )

    def sync_content(self, message: dict, selected_files: list, force: bool) -> int:
        raise ValueError(
            f"Content sync not supported for source_type {self.source_type.name}"
        )

    def ensure_content(
        self,
        datasource: dict,
        owner_email: str,
        selected_files: list,
        force: bool,
    ) -> int:
        return 0

    def collect_files(self, datasource: dict, owner_email: str) -> list[dict]:
        return []
