"""Pins the worker's JobFileState/JobFileErrorCode constants to the API enums.

The worker in ``sync/worker/`` can't import from the API package, so it
ships its own copies of ``JobFileState`` and ``JobFileErrorCode`` that
have to stay in sync with ``app.models``. Parses ``worker.py`` with
``ast`` (no imports run) and asserts the definitions match. Adding a new
state or code? Update both sides.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.models.enums import JobFileErrorCode, JobFileState

WORKER_PATH = (
    Path(__file__).resolve().parents[4] / "sync" / "worker" / "src" / "worker.py"
)


def _extract_worker_constants(class_name: str) -> dict[str, str]:
    """Return {name: value} from a constants class in worker.py."""
    tree = ast.parse(WORKER_PATH.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            constants: dict[str, str] = {}
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    constants[stmt.targets[0].id] = stmt.value.value
            return constants
    raise AssertionError(f"{class_name} class not found in worker.py")


def test_worker_jobfilestate_matches_api_enum() -> None:
    worker_states = _extract_worker_constants("JobFileState")
    api_states = {member.name: member.value for member in JobFileState}

    assert worker_states == api_states, (
        "JobFileState drift between worker and API. "
        f"Worker: {worker_states}\nAPI: {api_states}"
    )


def test_worker_jobfileerrorcode_matches_api_enum() -> None:
    worker_codes = _extract_worker_constants("JobFileErrorCode")
    api_codes = {member.name: member.value for member in JobFileErrorCode}

    assert worker_codes == api_codes, (
        "JobFileErrorCode drift between worker and API. "
        f"Worker: {worker_codes}\nAPI: {api_codes}"
    )
