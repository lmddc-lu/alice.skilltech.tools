from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from pii_filter.detector import Entity
from pii_filter.main import app


class FakeDetector:
    """Stand-in for `PiiDetector` so tests don't load the real model."""

    model_name = "fake-model"
    device = "-1"

    def __init__(self, entities_by_text: dict[str, list[Entity]] | None = None) -> None:
        self.entities_by_text = entities_by_text or {}
        self.calls: list[tuple[str, float]] = []

    def detect(self, text: str, min_score: float = 0.5) -> list[Entity]:
        self.calls.append((text, min_score))
        return [
            e for e in self.entities_by_text.get(text, []) if e["score"] >= min_score
        ]


@pytest.fixture
def fake() -> FakeDetector:
    return FakeDetector()


@pytest.fixture
def client(fake: FakeDetector) -> Iterator[TestClient]:
    # Bypass the real lifespan (which would download the model) by
    # injecting the fake detector directly. We use `with TestClient(...)` so
    # the app's own lifespan still runs cleanly when the fixture exits, but
    # we set state.detector both before and after to make sure neither the
    # lifespan nor a missing detector breaks the request handlers.
    app.state.detector = fake
    client = TestClient(app)
    yield client
    app.state.detector = None  # type: ignore[assignment]


def test_healthz_always_ok(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "model_loaded": True,
        "model_name": None,
        "device": None,
    }


def test_readyz_returns_model_metadata(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["model_name"] == "fake-model"
    assert body["device"] == "-1"


def test_readyz_503_when_no_model(client: TestClient) -> None:
    app.state.detector = None  # type: ignore[assignment]
    r = client.get("/readyz")
    assert r.status_code == 503


def test_redact_503_when_no_model(client: TestClient) -> None:
    app.state.detector = None  # type: ignore[assignment]
    r = client.post("/redact", json={"text": "hello"})
    assert r.status_code == 503


def test_redact_returns_redacted_text_and_entities(fake: FakeDetector) -> None:
    text = "Est-ce que Martine est sympa?"
    fake.entities_by_text[text] = [
        Entity(
            type="FIRST_NAME",
            start=11,
            end=18,
            score=0.99,
            surface="Martine",
        )
    ]
    app.state.detector = fake
    client = TestClient(app)

    r = client.post("/redact", json={"text": text})
    assert r.status_code == 200
    body = r.json()
    assert body["redacted_text"] == "Est-ce que [FIRST_NAME_1] est sympa?"
    assert len(body["entities"]) == 1
    assert body["entities"][0]["surface"] == "Martine"
    assert body["entities"][0]["type"] == "FIRST_NAME"


def test_redact_passes_min_score_to_detector(
    fake: FakeDetector, client: TestClient
) -> None:
    client.post("/redact", json={"text": "anything", "min_score": 0.8})
    assert fake.calls == [("anything", 0.8)]


def test_redact_min_score_filters_low_confidence(fake: FakeDetector) -> None:
    text = "Marie ou peut-être Paul"
    fake.entities_by_text[text] = [
        Entity(type="FIRST_NAME", start=0, end=5, score=0.99, surface="Marie"),
        Entity(type="FIRST_NAME", start=19, end=23, score=0.4, surface="Paul"),
    ]
    app.state.detector = fake
    client = TestClient(app)

    r = client.post("/redact", json={"text": text, "min_score": 0.5})
    body = r.json()
    assert len(body["entities"]) == 1
    assert body["entities"][0]["surface"] == "Marie"
    assert "Paul" in body["redacted_text"]  # not redacted


def test_redact_min_score_validation() -> None:
    client = TestClient(app)
    r = client.post("/redact", json={"text": "x", "min_score": 1.5})
    assert r.status_code == 422


def test_redact_empty_text_returns_no_entities(client: TestClient) -> None:
    r = client.post("/redact", json={"text": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["entities"] == []
    assert body["redacted_text"] == ""
