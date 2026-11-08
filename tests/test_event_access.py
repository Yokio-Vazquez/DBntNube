import secrets
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from src import main
from src.database import get_db_writer


class AuditSession:
    def __init__(self):
        self.pending = []
        self.persisted = []

    def execute(self, statement):
        self.pending.append(statement.compile().params)
        return SimpleNamespace(rowcount=1)

    def commit(self):
        self.persisted.extend(self.pending)
        self.pending.clear()


def test_event_permissions(monkeypatch):
    reader, writer = (secrets.token_urlsafe(32) for _ in range(2))
    monkeypatch.setenv("EVENTS_READER_TOKEN", reader)
    monkeypatch.setenv("EVENTS_WRITER_TOKEN", writer)
    read = Mock(return_value=[])
    page = Mock(return_value={"items": [], "nextCursor": None})
    create = Mock(return_value=True)
    monkeypatch.setattr(main, "query_events", read)
    monkeypatch.setattr(main, "query_events_page", page)
    monkeypatch.setattr(main, "create_event", create)
    session = AuditSession()

    def override_session():
        yield session

    previous_override = main.app.dependency_overrides.get(get_db_writer)
    monkeypatch.setitem(main.app.dependency_overrides, get_db_writer, override_session)
    client = TestClient(main.app)
    event = {
        "game_id": 1,
        "event_key": "fixture",
        "event_type": "start",
        "occurred_at": "2026-01-01T00:00:00Z",
        "source": "fixture",
    }
    if main.EventDocument.model_fields["schema_version"].default == 3:
        event["platform"] = "pc"
    try:
        for path in ("/events", "/events/page"):
            assert client.get(path, params={"game_id": 1}).status_code == 401
        assert client.post("/events", json=event).status_code == 401
        read.assert_not_called()
        page.assert_not_called()
        client.headers["Authorization"] = f"Bearer {reader}"
        assert client.post("/events", json=event).status_code == 403
        create.assert_not_called()
        assert client.get("/events?game_id=1").status_code == 200
        client.headers["Authorization"] = f"Bearer {writer}"
        assert client.post("/events", json=event).status_code == 201
        create.assert_called_once()
        monkeypatch.setenv("EVENTS_READER_TOKEN", writer)
        assert client.post("/events", json=event).status_code == 401
        create.assert_called_once()
    finally:
        if previous_override is None:
            main.app.dependency_overrides.pop(get_db_writer, None)
        else:
            main.app.dependency_overrides[get_db_writer] = previous_override

    audit_rows = [
        row for row in session.persisted
        if row.get("resource_type") == "events"
    ]
    assert len(audit_rows) == 7
    assert [row["outcome"] for row in audit_rows] == [
        "denied",
        "denied",
        "denied",
        "denied",
        "success",
        "success",
        "denied",
    ]
