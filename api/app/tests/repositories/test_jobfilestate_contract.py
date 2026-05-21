"""Pins the worker's JobFileState constants to the API enum.

The worker in ``sync/worker/`` can't import from the API package, so it
ships its own copy of ``JobFileState`` that has to stay in sync with
``app.models.JobFileState``. Parses ``worker.py`` with ``ast`` (no
imports run) and asserts the two definitions match. Adding a new state?
Update both sides.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.models.enums import JobFileState

WORKER_PATH = (
    Path(__file__).resolve().parents[4] / "sync" / "worker" / "src" / "worker.py"
)


def _extract_worker_states() -> dict[str, str]:
    """Return {name: value} from the worker's JobFileState class."""
    tree = ast.parse(WORKER_PATH.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "JobFileState":
            states: dict[str, str] = {}
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    states[stmt.targets[0].id] = stmt.value.value
            return states
    raise AssertionError("JobFileState class not found in worker.py")


def test_worker_jobfilestate_matches_api_enum() -> None:
    worker_states = _extract_worker_states()
    api_states = {member.name: member.value for member in JobFileState}

    assert worker_states == api_states, (
        "JobFileState drift between worker and API. "
        f"Worker: {worker_states}\nAPI: {api_states}"
    )
