import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from pii_filter.detector import DetectorProtocol, PiiDetector
from pii_filter.redaction import redact_with_placeholders
from pii_filter.schemas import (
    Entity,
    HealthResponse,
    RedactRequest,
    RedactResponse,
)

logger = logging.getLogger(__name__)

MODEL_NAME = os.environ["PII_MODEL_NAME"]
# -1 = CPU. For GPU, pass "0" (cuda:0) etc. Strings like "cuda" / "mps" also work.
DEVICE_ENV = os.getenv("PII_DEVICE", "-1")
STRIDE = int(os.getenv("PII_STRIDE", "64"))


def _parse_device(raw: str) -> int | str:
    try:
        return int(raw)
    except ValueError:
        return raw


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    device = _parse_device(DEVICE_ENV)
    app.state.detector = PiiDetector(
        model_name=MODEL_NAME, device=device, stride=STRIDE
    )
    yield


app = FastAPI(title="PII Filter", version="0.1.0", lifespan=lifespan)


def _detector(app: FastAPI) -> DetectorProtocol:
    detector: DetectorProtocol | None = getattr(app.state, "detector", None)
    if detector is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return detector


@app.get("/healthz", response_model=HealthResponse, tags=["health"])
def healthz() -> HealthResponse:
    return HealthResponse(status="ok", model_loaded=True)


@app.get("/readyz", response_model=HealthResponse, tags=["health"])
def readyz() -> HealthResponse:
    detector: DetectorProtocol | None = getattr(app.state, "detector", None)
    if detector is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return HealthResponse(
        status="ready",
        model_loaded=True,
        model_name=detector.model_name,
        device=detector.device,
    )


@app.post("/redact", response_model=RedactResponse, tags=["pii"])
def redact(req: RedactRequest) -> RedactResponse:
    detector = _detector(app)
    raw_entities = detector.detect(req.text, min_score=req.min_score)
    redacted_text, mapping = redact_with_placeholders(req.text, raw_entities)
    return RedactResponse(
        redacted_text=redacted_text,
        entities=[Entity(**e) for e in raw_entities],
        mapping=mapping,
    )
