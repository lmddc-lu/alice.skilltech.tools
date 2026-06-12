"""Prometheus metrics for the sync worker.

Exposes a /metrics HTTP endpoint on a dedicated port (default 9100) and
provides counters/histograms covering job lifecycle, per-file outcomes,
Haystack calls, and broker reconnects. Prefer counters and histograms
over gauges: workers claim and ack messages as soon as they are free, so
queue depth at the broker is ~0 at scrape time and gauge-based views
miss everything.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)


JOB_TYPE_METADATA_SYNC = "metadata_sync"
JOB_TYPE_CONTENT_SYNC = "content_sync"
JOB_TYPE_INGESTION = "ingestion"

JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"
JOB_STATUS_AUTH_ERROR = "auth_error"

FILE_STAGE_DOWNLOAD = "download"
FILE_STAGE_INGEST = "ingest"

HAYSTACK_OUTCOME_OK = "ok"
HAYSTACK_OUTCOME_TIMEOUT = "timeout"
HAYSTACK_OUTCOME_ERROR = "error"

# terminal per-file states worth counting (mirrors JobFileState in worker.py).
TERMINAL_FILE_STATES: frozenset[str] = frozenset({"ingested", "failed", "skipped"})


JOBS_PROCESSED = Counter(
    "worker_jobs_processed_total",
    "Worker job message handler completions, by job type and terminal status.",
    ["job_type", "status"],
)

JOB_DURATION = Histogram(
    "worker_job_duration_seconds",
    "End-to-end duration of a worker job handler, by job type.",
    ["job_type"],
    # long-tail: metadata sync is seconds, ingestion can be minutes-to-hours.
    buckets=(0.5, 1, 5, 15, 30, 60, 300, 900, 1800, 3600, 7200),
)

JOB_ACTIVE = Gauge(
    "worker_job_active",
    "Jobs currently being processed by this worker process, by job type.",
    ["job_type"],
)

FILES_PROCESSED = Counter(
    "worker_files_processed_total",
    "Per-file terminal state transitions inside ingestion jobs.",
    ["state", "error_code"],
)

FILE_PROCESSING_DURATION = Histogram(
    "worker_file_processing_duration_seconds",
    "Per-file processing duration, by stage (download or ingest).",
    ["stage"],
    buckets=(0.1, 0.5, 1, 5, 15, 30, 60, 300, 900, 1800),
)

CHUNKS_CREATED = Counter(
    "worker_chunks_created_total",
    "Number of document chunks produced by ingestion.",
)

HAYSTACK_REQUESTS = Counter(
    "worker_haystack_requests_total",
    "Outbound HTTP calls to Hayhooks, by outcome.",
    ["outcome"],
)

HAYSTACK_REQUEST_DURATION = Histogram(
    "worker_haystack_request_duration_seconds",
    "Outbound HTTP call duration to Hayhooks (any endpoint).",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

RABBITMQ_RECONNECTS = Counter(
    "worker_rabbitmq_reconnects_total",
    "Reconnect attempts triggered by the consume loop after a broker error.",
)


def start_metrics_server(port: int) -> None:
    """Start the Prometheus exposition HTTP server in a background thread.

    Idempotent across imports because prometheus_client raises on a
    duplicate bind — callers should only invoke this once at startup.
    """
    start_http_server(port)
    logger.info("Worker metrics server listening on :%d/metrics", port)


@contextmanager
def track_job(job_type: str) -> Iterator[dict]:
    """Time a job handler and record its terminal status.

    Yields a mutable dict; assign to ``status["value"]`` in each except
    branch so the finally block records the right label. Defaults to
    "completed" — the success path needs no extra code.
    """
    status: dict = {"value": JOB_STATUS_COMPLETED}
    JOB_ACTIVE.labels(job_type=job_type).inc()
    start = time.perf_counter()
    try:
        yield status
    finally:
        elapsed = time.perf_counter() - start
        JOB_DURATION.labels(job_type=job_type).observe(elapsed)
        JOB_ACTIVE.labels(job_type=job_type).dec()
        JOBS_PROCESSED.labels(job_type=job_type, status=status["value"]).inc()


def record_file_state(state: str, error_code: str | None = None) -> None:
    """Increment the file counter for terminal states; ignore intermediate ones."""
    if state not in TERMINAL_FILE_STATES:
        return
    FILES_PROCESSED.labels(state=state, error_code=error_code or "").inc()


@contextmanager
def track_file_stage(stage: str) -> Iterator[None]:
    """Time a per-file processing stage (download or ingest)."""
    start = time.perf_counter()
    try:
        yield
    finally:
        FILE_PROCESSING_DURATION.labels(stage=stage).observe(
            time.perf_counter() - start
        )
