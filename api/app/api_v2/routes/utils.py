import logging

import httpx
from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.storage import StorageManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/utils", tags=["utils"])


class HealthCheckResponse(BaseModel):
    healthy: bool
    errors: list[str] = []


@router.get("/health-check/")
async def health_check(response: Response) -> HealthCheckResponse:
    """Returns 200 only when all critical dependencies are reachable."""
    errors: list[str] = []

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.HAYSTACK_INFERENCE_URL}/status", timeout=5.0
            )
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Hayhooks health check failed: {e}")
        errors.append("Hayhooks inference API unreachable")

    try:
        storage = StorageManager()
        storage.check_connection()
    except Exception as e:
        logger.warning(f"S3 health check failed: {e}")
        errors.append("S3 storage unreachable")

    if errors:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthCheckResponse(healthy=False, errors=errors)

    return HealthCheckResponse(healthy=True)
