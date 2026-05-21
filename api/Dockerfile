# syntax=docker/dockerfile:1

# ---------- Builder ----------
FROM python:3.13-slim AS builder

# Ref: https://docs.astral.sh/uv/guides/integration/docker/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

WORKDIR /app

# Install dependencies in their own layer (cached when only project code changes)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Install the project itself
COPY ./pyproject.toml ./uv.lock /app/
COPY ./app /app/app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# ---------- Runtime ----------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc

# curl is required by the docker-compose healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app
COPY ./alembic.ini /app/
COPY ./scripts /app/scripts

RUN adduser --disabled-password --no-create-home --gecos "" appuser
USER appuser

# sh -c wrapper so we can clean stale per-PID metric files from the previous
# container run before workers start. exec preserves PID 1 signal handling.
CMD ["sh", "-c", "mkdir -p \"$PROMETHEUS_MULTIPROC_DIR\" && rm -f \"$PROMETHEUS_MULTIPROC_DIR\"/* && exec fastapi run --workers 8 app/main.py --host 0.0.0.0"]
