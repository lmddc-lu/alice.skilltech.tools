"""Publisher for job_progress_updates messages.

Centralises the wire payload for progress and per-file state transitions.
Hosts the debounced Haystack tick handler so per-file state lives in a
closure instead of being threaded through partials.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from messaging.rabbitmq import QueueNames
from metrics import record_file_state

logger = logging.getLogger(__name__)


class ProgressPublisher:
    """Publish progress and per-file state to job_progress_updates.

    Takes a get_client callable, not the client directly, so the publisher
    can be wired before RabbitMQClient connects.
    """

    def __init__(self, get_client: Callable[[], Any]):
        self._get_client = get_client

    def publish_progress(
        self,
        job_id,
        *,
        message: str | None = None,
        total_files: int | None = None,
        file: dict | None = None,
    ) -> None:
        """Bump progress_updated_at on the API side.

        Pass file to record a per-file state transition (see
        app.models.JobFileState for valid states).
        """
        if not job_id:
            return
        payload: dict = {"job_id": str(job_id)}
        if message is not None:
            payload["message"] = message
        if total_files is not None:
            payload["total_files"] = total_files
        if file is not None:
            payload["file"] = file
        try:
            self._get_client().publish(QueueNames.JOB_PROGRESS_UPDATES, payload)
        except Exception as e:
            logger.warning(f"Failed to publish progress update: {e}")

    def publish_file_state(
        self,
        job_id,
        *,
        file_id,
        filename: str,
        state: str,
        error_message: str | None = None,
        error_detail: str | None = None,
        error_code: str | None = None,
    ) -> None:
        """Publish a per-file state transition.

        If upstream gives no file_id, synthesize one from the filename
        (prefixed "synth:") so the JobFile row gets created and subsequent
        transitions mutate the same row.
        """
        if file_id:
            external_id = str(file_id)
        else:
            external_id = f"synth:{filename}"
            logger.debug(
                f"No file_id for {filename!r}; using synthetic key {external_id!r}"
            )
        record_file_state(state, error_code)
        self.publish_progress(
            job_id,
            file={
                "external_file_id": external_id,
                "filename": filename,
                "state": state,
                "error_message": error_message,
                "error_detail": error_detail,
                "error_code": error_code,
            },
        )

    def haystack_tick_handler(
        self,
        job_id,
        filename: str,
        *,
        pct_step: int,
        max_interval_seconds: float,
    ) -> Callable[[str, int, dict], None]:
        """Return a debounced progress callback for one file's Haystack run.

        Ticks within pct_step and max_interval_seconds of the last published
        tick are dropped; the rest flush a progress message so
        progress_updated_at keeps moving on the API side.
        """
        state = {"pct": -pct_step, "t": 0.0}

        def on_tick(stage: str, pct: int, _raw: dict) -> None:
            now = time.monotonic()
            pct_advance = abs(pct - state["pct"])
            elapsed = now - state["t"]
            if pct_advance < pct_step and elapsed < max_interval_seconds:
                return
            state["pct"] = pct
            state["t"] = now
            self.publish_progress(job_id, message=f"{filename}: {stage} ({pct}%)")

        return on_tick
