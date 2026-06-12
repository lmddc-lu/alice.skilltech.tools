.PHONY: help install lock lint format typecheck test test-cov check serve clean

help:
	@echo "Available targets:"
	@echo "  install    - Install dependencies (prod + dev) via uv"
	@echo "  lock       - Regenerate uv.lock from pyproject.toml"
	@echo "  lint       - Run ruff check + format check"
	@echo "  format     - Auto-fix lint issues and format code"
	@echo "  typecheck  - Run mypy"
	@echo "  test       - Run pytest"
	@echo "  test-cov   - Run pytest with coverage report"
	@echo "  check      - Run lint + test (CI equivalent)"
	@echo "  serve      - Run the service locally on :8000 (CPU)"
	@echo "  clean      - Remove caches and build artifacts"

install:
	uv sync --frozen

lock:
	uv lock

lint:
	uv run ruff check src tests
	uv run ruff format src tests --check

format:
	uv run ruff check src tests --fix
	uv run ruff format src tests

typecheck:
	uv run mypy src

test:
	uv run pytest

test-cov:
	uv run coverage run --source=src -m pytest
	uv run coverage report --show-missing

check: lint test

serve:
	uv run uvicorn pii_filter.main:app --host 0.0.0.0 --port 8000 --reload

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
