"""Pin the API and worker copies of url_validation.py.

The two files are vendored verbatim because the API and worker have no
shared library. CI fails as soon as either copy drifts so the worker
can't validate URLs differently from the API.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
API_COPY = REPO_ROOT / "api" / "app" / "services" / "url_validation.py"
WORKER_COPY = REPO_ROOT / "sync" / "worker" / "src" / "core" / "url_validation.py"


def test_api_and_worker_validators_match():
    api_text = API_COPY.read_text()
    worker_text = WORKER_COPY.read_text()
    assert api_text == worker_text, (
        f"{API_COPY} and {WORKER_COPY} have drifted. "
        "Re-vendor by copying one over the other; the two must stay byte-identical."
    )
