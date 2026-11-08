import secrets
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from src import main
from src.audit import complete_event_audit, reconciled_event_outcome
from src.database import get_db_writer


class AuditSession:
    def __init__(self):
        self.pending = []
        self.persisted = []

    def execute(self, statement):
        params = statement.compile().params
        self.pending.append({"_table": statement.table.name, **params})
        return SimpleNamespace(rowcount=1)

    def commit(self):
        self.persisted.extend(self.pending)
        self.pending.clear()

    def rollback(self):
        self.pending.clear()


def audit_client(monkeypatch):
    reader = secrets.token_urlsafe(32)
    writer = secrets.token_urlsafe(32)
    monkeypatch.setenv("EVENTS_READER_TOKEN", reader)
    monkeypatch.setenv("EVENTS_WRITER_TOKEN", writer)
    session = AuditSession()

    def override_session():
        yield session

    previous_override = main.app.dependency_overrides.get(get_db_writer)
    monkeypatch.setitem(main.app.dependency_overrides, get_db_writer, override_session)

    def restore_override():
        if previous_override is None:
            main.app.dependency_overrides.pop(get_db_writer, None)
        else:
            main.app.dependency_overrides[get_db_writer] = previous_override

    return TestClient(main.app), session, reader, writer, restore_override


def event_payload():
    payload = {
        "game_id": 917,
        "event_key": "m09-audit-synthetic",
        "event_type": "session_started",
        "occurred_at": "2026-11-07T12:00:00Z",
        "source": "synthetic-fixture",
    }
    if main.EventDocument.model_fields["schema_version"].default == 3:
        payload["platform"] = "pc"
    return payload


def assert_audit(session, *, actor, action, outcome):
    matching = [
        row for row in session.persisted
        if row.get("resource_type") == "events"
    ]
    assert matching
    row = matching[-1]
    assert row["actor_id"] == actor
    assert row["action"] == action
    assert row["resource_type"] == "events"
    assert row["outcome"] == outcome
    return row


def test_reader_create_denial_is_audited_without_request_marker(monkeypatch):
    client, session, reader, _, restore = audit_client(monkeypatch)
    marker = "m09-header-marker-" + secrets.token_hex(8)
    try:
        response = client.post(
            "/events",
            json=event_payload(),
            headers={
                "Authorization": f"Bearer {reader}",
                "X-Synthetic-Marker": marker,
            },
        )
    finally:
        restore()

    assert response.status_code == 403
    row = assert_audit(session, actor="reader", action="create", outcome="denied")
    assert marker not in str(row)
    assert len(session.persisted) == 1


def test_invalid_authentication_is_audited_as_anonymous(monkeypatch):
    client, session, _, _, restore = audit_client(monkeypatch)
    try:
        response = client.get("/events", params={"game_id": 917})
    finally:
        restore()

    assert response.status_code == 401
    assert_audit(session, actor="anonymous", action="read", outcome="denied")
    assert len(session.persisted) == 1


def test_successful_reads_and_creates_are_audited_once(monkeypatch):
    client, session, _, writer, restore = audit_client(monkeypatch)
    monkeypatch.setattr(main, "query_events", lambda game_id: [])
    monkeypatch.setattr(
        main,
        "query_events_page",
        lambda game_id, limit, cursor: {
            "items": [],
            "nextCursor": None,
            "scannedCount": 0,
        },
    )
    def create_stored_event(event, *, audit_operation_id):
        assert any(
            row["_table"] == "event_audit_outbox"
            and row.get("status") == "pending"
            for row in session.persisted
        )
        assert audit_operation_id
        return True

    monkeypatch.setattr(main, "create_event", create_stored_event)
    headers = {"Authorization": f"Bearer {writer}"}
    try:
        all_events = client.get("/events", params={"game_id": 917}, headers=headers)
        page = client.get("/events/page", params={"game_id": 917}, headers=headers)
        created = client.post("/events", json=event_payload(), headers=headers)
    finally:
        restore()

    assert all_events.status_code == page.status_code == 200
    assert created.status_code == 201
    audit_rows = [
        row for row in session.persisted if row["_table"] == "audit_logs"
    ]
    assert [(row["action"], row["outcome"]) for row in audit_rows] == [
        ("read", "success"),
        ("read", "success"),
        ("create", "success"),
    ]
    outbox_rows = [
        row for row in session.persisted
        if row["_table"] == "event_audit_outbox"
    ]
    assert len(outbox_rows) == 2
    assert any(row.get("status") == "pending" for row in outbox_rows)
    assert any(row.get("status") == "completed" for row in outbox_rows)


def test_duplicate_and_storage_unavailable_have_distinct_audit_outcomes(monkeypatch):
    client, session, _, writer, restore = audit_client(monkeypatch)
    monkeypatch.setattr(
        main,
        "create_event",
        lambda event, audit_operation_id: False,
    )
    headers = {"Authorization": f"Bearer {writer}"}
    try:
        duplicate = client.post("/events", json=event_payload(), headers=headers)
        monkeypatch.setattr(
            main,
            "create_event",
            Mock(side_effect=main.BotoCoreError()),
        )
        unavailable = client.post(
            "/events",
            json={**event_payload(), "event_key": "m09-unavailable"},
            headers=headers,
        )
    finally:
        restore()

    assert duplicate.status_code == 409
    assert unavailable.status_code == 503
    audit_rows = [
        row for row in session.persisted if row["_table"] == "audit_logs"
    ]
    assert [(row["outcome"], row["action"]) for row in audit_rows] == [
        ("conflict", "create"),
        ("unavailable", "create"),
    ]


def test_created_event_with_failed_audit_commit_is_reconciled(monkeypatch):
    class FailFinalCommitSession(AuditSession):
        def __init__(self):
            super().__init__()
            self.commit_count = 0
            self.fail_final_commit = True

        def commit(self):
            self.commit_count += 1
            if self.commit_count == 2 and self.fail_final_commit:
                raise SQLAlchemyError("synthetic audit database failure")
            super().commit()

    client, _, _, writer, restore = audit_client(monkeypatch)
    session = FailFinalCommitSession()

    def override_session():
        yield session

    monkeypatch.setitem(
        main.app.dependency_overrides,
        get_db_writer,
        override_session,
    )
    stored = {}

    def create_stored_event(event, *, audit_operation_id):
        stored.update(
            game_id=event.game_id,
            event_key=event.event_key,
            _audit_operation_id=audit_operation_id,
        )
        return True

    monkeypatch.setattr(main, "create_event", create_stored_event)
    try:
        response = client.post(
            "/events",
            json=event_payload(),
            headers={"Authorization": f"Bearer {writer}"},
        )
    finally:
        restore()

    assert response.status_code == 503, response.json()
    assert stored["_audit_operation_id"]
    pending = next(
        row for row in session.persisted
        if row["_table"] == "event_audit_outbox"
    )
    assert pending["status"] == "pending"

    outcome = reconciled_event_outcome(
        pending["operation_id"],
        stored,
    )
    assert outcome == "success"
    assert reconciled_event_outcome(pending["operation_id"], None) == "unavailable"
    assert reconciled_event_outcome(
        pending["operation_id"],
        {"_audit_operation_id": "different-operation"},
    ) == "conflict"
    session.fail_final_commit = False
    complete_event_audit(
        session,
        operation_id=pending["operation_id"],
        actor_id="writer",
        game_id=event_payload()["game_id"],
        event_key=event_payload()["event_key"],
        outcome=outcome,
    )

    audit_rows = [
        row for row in session.persisted if row["_table"] == "audit_logs"
    ]
    assert [(row["action"], row["outcome"]) for row in audit_rows] == [
        ("create", "success")
    ]
