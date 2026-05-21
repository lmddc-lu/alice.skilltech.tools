.PHONY: help install lint format typecheck test test-cov check smoke clean

help:
	@echo "Available targets:"
	@echo "  install    - Install dependencies (prod + dev) via uv"
	@echo "  lint       - Run ruff check + format check"
	@echo "  format     - Auto-fix lint issues and format code"
	@echo "  typecheck  - Run mypy only"
	@echo "  test       - Run pytest"
	@echo "  test-cov   - Run pytest with coverage report"
	@echo "  check      - Run lint + test (CI equivalent)"
	@echo "  smoke      - Run end-to-end smoke test against running service"
	@echo "  clean      - Remove caches and build artifacts"

install:
	uv sync --frozen

lint:
	uv run ruff check src
	uv run ruff format src --check

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

smoke:
	./test.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
