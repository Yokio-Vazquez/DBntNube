from fastapi.testclient import TestClient

from src.main import app
from src.schemas import EventDocument
import src.main as main_module


client = TestClient(app)


def test_new_event_documents_default_to_v2():
    event = EventDocument(
        game_id=1,
        event_key="session_started#2026-10-11T10:00:00Z#v2-001",
        event_type="session_started",
        occurred_at="2026-10-11T10:00:00Z",
        source="synthetic-fixture",
    )

    assert event.model_dump(by_alias=True)["schemaVersion"] == 2


def test_events_returns_v2_document(monkeypatch):
    event = {
        "game_id": 1,
        "event_key": "session_started#2026-10-11T10:00:00Z#v2-001",
        "event_type": "session_started",
        "occurred_at": "2026-10-11T10:00:00Z",
        "source": "synthetic-fixture",
        "schemaVersion": 2,
    }
    monkeypatch.setattr(main_module, "query_events", lambda game_id: [event])

    response = client.get("/events", params={"game_id": 1})

    assert response.status_code == 200
    assert response.json() == [event]


def test_events_defaults_legacy_document_to_v1(monkeypatch):
    event = {
        "game_id": 1,
        "event_key": "session_started#2026-09-27T10:00:00Z#fixture-001",
        "event_type": "session_started",
        "occurred_at": "2026-09-27T10:00:00Z",
        "source": "synthetic-fixture",
    }
    monkeypatch.setattr(main_module, "query_events", lambda game_id: [event])

    response = client.get("/events", params={"game_id": 1})

    assert response.status_code == 200
    assert response.json() == [{**event, "schemaVersion": 1}]


def test_events_rejects_unsupported_document_version(monkeypatch):
    event = {
        "game_id": 1,
        "event_key": "session_started#2026-10-11T10:00:00Z#v3-001",
        "event_type": "session_started",
        "occurred_at": "2026-10-11T10:00:00Z",
        "source": "synthetic-fixture",
        "schemaVersion": 3,
    }
    monkeypatch.setattr(main_module, "query_events", lambda game_id: [event])

    response = client.get("/events", params={"game_id": 1})

    assert response.status_code == 500
    assert "version no soportada" in response.json()["detail"]