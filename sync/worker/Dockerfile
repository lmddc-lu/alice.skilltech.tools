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

# `package = false` in pyproject.toml only dependencies are installed, no project build
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked

# ---------- Runtime ----------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src /app

RUN mkdir -p /tmp/syncs

RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser /tmp/syncs
USER appuser

CMD ["python", "main.py"]
