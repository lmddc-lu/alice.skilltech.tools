FROM deepset/hayhooks:v1.19.2

RUN apt-get update && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11.4 /uv /uvx /bin/

# Install additional dependencies into the base image's existing venv
ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    VIRTUAL_ENV=/opt/venv uv pip install -r pyproject.toml

COPY src/pipeline_wrappers /pipelines
COPY src/imports /python

ENV HAYHOOKS_PIPELINES_DIR=/pipelines
ENV HAYHOOKS_ADDITIONAL_PYTHON_PATH=/python

RUN adduser --disabled-password --gecos "" appuser
USER appuser

CMD ["hayhooks", "run", "--host", "0.0.0.0", "--workers", "8"]
