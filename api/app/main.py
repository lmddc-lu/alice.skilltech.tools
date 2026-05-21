import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlmodel import Session
from starlette.middleware.cors import CORSMiddleware

from app.api_v2.main import api_v2_router
from app.api_v2.routes.openai_compat import router as openai_compat_router
from app.core.config import settings
from app.core.db import engine
from app.core.metrics import PrometheusMiddleware, metrics_endpoint
from app.core.rate_limit import limiter
from app.repositories.job import JobRepository
from app.services.messaging_service import broadcast_job_cancellations
from app.services.scheduler_service import scheduler_service
from app.services.url_validation import log_effective_allowlists

logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log_effective_allowlists()
    # mark jobs left running/pending from before reboot as stalled
    with Session(engine) as session:
        job_repo = JobRepository(session)
        stalled = job_repo.mark_all_running_as_stalled()
        if stalled:
            try:
                await broadcast_job_cancellations(
                    settings.RABBITMQ_URL, [job.id for job in stalled]
                )
            except Exception:
                logger.exception("Startup: failed to broadcast cancellations")

    scheduler_service.start()
    yield
    scheduler_service.shutdown()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

app.include_router(api_v2_router, prefix=settings.API_V2_STR)
app.include_router(openai_compat_router, prefix="/api")

app.add_middleware(PrometheusMiddleware)
app.add_api_route(
    "/metrics", metrics_endpoint, tags=["metrics"], include_in_schema=False
)
