"""Per-job logging context.

The consume loop enters job_context() at message claim, and every log
record emitted while the job runs — from any module — carries
``job_id=… queue=…``. With three worker replicas, grepping the container
logs for ``job_id=<id>`` reconstructs the full timeline of a failed job,
including the lines that weren't errors.

JobContextFilter must be attached to the root handler and the log format
must include ``%(job_context)s`` (see main.py).
"""

from __future__ import annotations

import contextvars
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

_JOB_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_job_id", default=None
)
_QUEUE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_queue", default=None
)


class JobContextFilter(logging.Filter):
    """Inject ``record.job_context`` (' [job_id=… queue=…]' or '')."""

    def filter(self, record: logging.LogRecord) -> bool:
        parts = []
        job_id = _JOB_ID.get()
        if job_id:
            parts.append(f"job_id={job_id}")
        queue = _QUEUE.get()
        if queue:
            parts.append(f"queue={queue}")
        record.job_context = f" [{' '.join(parts)}]" if parts else ""
        return True


@contextmanager
def job_context(job_id: str | None, queue: str | None) -> Iterator[None]:
    job_token = _JOB_ID.set(job_id)
    queue_token = _QUEUE.set(queue)
    try:
        yield
    finally:
        _JOB_ID.reset(job_token)
        _QUEUE.reset(queue_token)


def peek_job_id(body: bytes) -> str | None:
    """Best-effort job_id from a raw message body, for logging only."""
    try:
        message = json.loads(body)
    except Exception:
        return None
    if isinstance(message, dict) and message.get("job_id"):
        return str(message["job_id"])
    return None
