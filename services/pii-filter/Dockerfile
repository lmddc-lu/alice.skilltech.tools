FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/models

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.4 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY src /app/src

RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /models \
    && chown appuser:appuser /models
USER appuser

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    PII_DEVICE="-1"

EXPOSE 8000
CMD ["uvicorn", "pii_filter.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
