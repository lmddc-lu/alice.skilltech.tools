"""Prometheus metrics: HTTP middleware and /metrics endpoint.

Pure-ASGI middleware (not BaseHTTPMiddleware) so streaming responses
(notably openai_compat chat completions) pass through unbuffered.

Honors PROMETHEUS_MULTIPROC_DIR for multi-worker deployments, falls
back to single-process mode when unset.
"""

import os
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from prometheus_client import REGISTRY as DEFAULT_REGISTRY

# paths excluded from metrics (scrape noise and healthcheck).
EXCLUDED_PATHS: frozenset[str] = frozenset({"/metrics", "/api/v2/utils/health-check/"})

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests, by method, route template, and status code.",
    ["method", "handler", "status"],
)
DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds, by method and route template.",
    ["method", "handler"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
IN_PROGRESS = Gauge(
    "http_requests_inprogress",
    "In-flight HTTP requests, by method.",
    ["method"],
    multiprocess_mode="livesum",
)


# --- Job lifecycle metrics --------------------------------------------------
#
# Counters/histograms over job state transitions so the dashboard keeps a
# signal even when broker queue depth is ~0 (jobs picked up too fast for
# RabbitMQ gauges to be useful). Recorded inside JobRepository so every
# state change funnels through the same code path.

JOBS_ENQUEUED = Counter(
    "jobs_enqueued_total",
    "Jobs created (PENDING) on the API side, by job type.",
    ["job_type"],
)

JOBS_COMPLETED = Counter(
    "jobs_completed_total",
    "Jobs reaching a terminal state, by job type and final status.",
    ["job_type", "status"],
)

JOB_PENDING_SECONDS = Histogram(
    "job_pending_seconds",
    "Time from job creation to first transition to RUNNING (queue wait).",
    ["job_type"],
    buckets=(0.5, 1, 5, 15, 30, 60, 300, 900, 1800, 3600),
)

JOB_TOTAL_DURATION_SECONDS = Histogram(
    "job_total_duration_seconds",
    "Wall-clock time from job creation to terminal state.",
    ["job_type", "status"],
    buckets=(1, 5, 15, 30, 60, 300, 900, 1800, 3600, 7200, 14400),
)

JOB_FAILURES = Counter(
    "job_failures_total",
    "Failed jobs broken down by error kind classified from the error message.",
    ["job_type", "error_kind"],
)

# shared-source gauge: every uvicorn worker reads the same DB and writes
# the same value. "max" makes the aggregated reading equal to the latest
# value any worker observed; "livesum" would multiply it by worker count.
JOBS_IN_STATE = Gauge(
    "jobs_in_state",
    "Number of jobs currently in each lifecycle state (refreshed periodically).",
    ["state"],
    multiprocess_mode="max",
)


# --- Scheduler & monitoring metrics ----------------------------------------

SCHEDULER_TASK_STALLED_SWEEP = "stalled_jobs_sweep"
SCHEDULER_TASK_RECONCILE_CHATBOTS = "reconcile_chatbots"
SCHEDULER_TASK_CHATBOT_REINDEX = "chatbot_reindex"
SCHEDULER_TASK_JOBS_IN_STATE_REFRESH = "jobs_in_state_refresh"

SCHEDULER_OUTCOME_OK = "ok"
SCHEDULER_OUTCOME_ERROR = "error"

SCHEDULER_RUNS = Counter(
    "scheduler_runs_total",
    "APScheduler task firings handled by SchedulerService, by task and outcome.",
    ["task", "outcome"],
)

SCHEDULER_RUN_DURATION = Histogram(
    "scheduler_run_duration_seconds",
    "Wall-clock duration of each SchedulerService task firing, by task.",
    ["task"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300),
)

SCHEDULER_STALLED_JOBS_SWEPT = Counter(
    "scheduler_stalled_jobs_swept_total",
    "Jobs marked stalled by the periodic sweep (sum across all sweeps).",
)

MONITORING_RABBITMQ_POLL = Counter(
    "monitoring_rabbitmq_poll_total",
    "Outbound polls of the RabbitMQ management API, by endpoint and outcome.",
    ["endpoint", "outcome"],
)


@contextmanager
def track_scheduler_run(task: str) -> Iterator[None]:
    """Time and count a scheduler task firing.

    Records outcome=error if the body raises, then re-raises so the caller
    still sees the failure. Always records duration.
    """
    outcome = SCHEDULER_OUTCOME_OK
    start = time.perf_counter()
    try:
        yield
    except Exception:
        outcome = SCHEDULER_OUTCOME_ERROR
        raise
    finally:
        SCHEDULER_RUN_DURATION.labels(task=task).observe(time.perf_counter() - start)
        SCHEDULER_RUNS.labels(task=task, outcome=outcome).inc()


ERROR_KIND_AUTH = "auth"
ERROR_KIND_CONNECTION = "connection"
ERROR_KIND_TIMEOUT = "timeout"
ERROR_KIND_EMPTY_CONTENT = "empty_content"
ERROR_KIND_CANCELLED = "cancelled"
ERROR_KIND_OTHER = "other"


def classify_error_kind(error_message: str | None) -> str:
    """Bucket a free-text error into a stable label for failure dashboards.

    Order matters: auth before connection (a Moodle auth error often contains
    "connection" too). Keep the bucket count small so the time series doesn't
    fan out, anything unmatched goes to "other".
    """
    if not error_message:
        return ERROR_KIND_OTHER
    msg = error_message.lower()
    if "auth" in msg:
        return ERROR_KIND_AUTH
    if "timeout" in msg or "timed out" in msg:
        return ERROR_KIND_TIMEOUT
    if "connection" in msg or "connect" in msg or "unreachable" in msg:
        return ERROR_KIND_CONNECTION
    if "empty" in msg or "no text content" in msg:
        return ERROR_KIND_EMPTY_CONTENT
    if "cancel" in msg:
        return ERROR_KIND_CANCELLED
    return ERROR_KIND_OTHER


Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class PrometheusMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in EXCLUDED_PATHS:
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        status_holder = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        IN_PROGRESS.labels(method).inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            # fall back to a fixed bucket for unmatched requests (404s)
            # to keep label cardinality bounded.
            route = scope.get("route")
            handler = getattr(route, "path", None) or "<unmatched>"
            DURATION.labels(method, handler).observe(elapsed)
            REQUESTS.labels(method, handler, str(status_holder["code"])).inc()
            IN_PROGRESS.labels(method).dec()


def metrics_endpoint() -> Response:
    """Render Prometheus exposition, aggregating across workers when
    PROMETHEUS_MULTIPROC_DIR is set."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = DEFAULT_REGISTRY
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
