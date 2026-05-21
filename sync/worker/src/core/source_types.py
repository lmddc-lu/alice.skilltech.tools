"""Datasource type enum shared across the worker.

Integer values are pinned to the wire protocol (smallint over RabbitMQ).
The API side mirrors this; renaming a member breaks the wire protocol.
"""

from __future__ import annotations

from enum import IntEnum


class SourceType(IntEnum):
    """Datasource provider. Integer values are pinned to the wire protocol."""

    MOODLE = 1
    NEXTCLOUD = 2
    FILE = 3

    @classmethod
    def parse(cls, value: int | None) -> SourceType:
        """Coerce an int from a message body into the enum.

        Raises ValueError with a worker-friendly message so the catch-all
        handler logs something operators can act on.
        """
        if value is None:
            raise ValueError("source_type is missing from message")
        try:
            return cls(value)
        except ValueError:
            valid = ", ".join(f"{m.name}={m.value}" for m in cls)
            raise ValueError(
                f"Unsupported source_type: {value!r} (expected one of: {valid})"
            )
