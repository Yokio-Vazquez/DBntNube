import secrets

from fastapi.testclient import TestClient

from src.audit import record_audit
from src.database import get_db_writer
from src.main import app


client = TestClient(app)


def test_delete_metric_records_audit_entry(monkeypatch):
    class Result:
        def scalar_one_or_none(self):
            return True

    class SessionStub:
        def __init__(self):
            self.entries = []
            self.statements = []
            self.committed = False

        def execute(self, statement):
            self.statements.append(statement)
            return Result()

        def commit(self):
            self.committed = True

    session = SessionStub()

    def override_get_db_writer():
        yield session

    monkeypatch.setitem(app.dependency_overrides, get_db_writer, override_get_db_writer)
    try:
        response = client.delete("/metrics/42", headers={"X-Actor-ID": "operator-7"})
    finally:
        app.dependency_overrides.pop(get_db_writer, None)

    assert response.status_code == 204
    assert session.committed is True
    assert len(session.statements) == 2
    audit_statement = next(
        statement for statement in session.statements
        if getattr(getattr(statement, "table", None), "name", None) == "audit_logs"
    )
    audit_values = audit_statement.compile().params
    assert audit_values["actor_id"] == "operator-7"
    assert audit_values["action"] == "metric.soft_delete"
    assert audit_values["resource_id"] == "42"
    assert audit_values["outcome"] == "success"


def test_delete_missing_metric_records_failure(monkeypatch):
    class Result:
        def scalar_one_or_none(self):
            return False

    class SessionStub:
        def __init__(self):
            self.statements = []
            self.committed = False

        def execute(self, statement):
            self.statements.append(statement)
            return Result()

        def commit(self):
            self.committed = True

    session = SessionStub()

    def override_get_db_writer():
        yield session

    monkeypatch.setitem(app.dependency_overrides, get_db_writer, override_get_db_writer)
    try:
        response = client.delete("/metrics/404", headers={"X-Actor-ID": "operator-7"})
    finally:
        app.dependency_overrides.pop(get_db_writer, None)

    assert response.status_code == 404
    assert session.committed is True
    audit_statement = next(
        statement for statement in session.statements
        if getattr(getattr(statement, "table", None), "name", None) == "audit_logs"
    )
    audit_values = audit_statement.compile().params
    assert audit_values["outcome"] == "failure"
    assert audit_values["details"] == {"reason": "not_found"}


def test_audit_redacts_secrets_from_sensitive_request_data():
    class SessionStub:
        def execute(self, statement):
            self.statement = statement

    session = SessionStub()
    password_value = secrets.token_urlsafe(32)
    token_value = secrets.token_urlsafe(32)
    secret_value = secrets.token_urlsafe(32)
    entry = record_audit(
        session,
        actor_id="operator-7",
        action="user.create",
        resource_type="user",
        resource_id="user-12",
        outcome="success",
        details={
            "username": "sample-user",
            "password": password_value,
            "access_token": token_value,
            "profile": {"clientSecret": secret_value},
        },
    )

    serialized_details = str(entry.details) + str(session.statement.compile().params)
    assert entry.details["username"] == "sample-user"
    assert entry.details["password"] == "[REDACTED]"
    assert entry.details["access_token"] == "[REDACTED]"
    assert entry.details["profile"]["clientSecret"] == "[REDACTED]"
    assert password_value not in serialized_details
    assert token_value not in serialized_details
    assert secret_value not in serialized_details


def test_audit_records_minimal_optional_fields():
    class SessionStub:
        def execute(self, statement):
            self.statement = statement

    session = SessionStub()
    entry = record_audit(
        session,
        actor_id=None,
        action="system.check",
        resource_type="system",
        resource_id=None,
        outcome="success",
        details=None,
    )

    persisted_values = session.statement.compile().params
    assert entry.actor_id is None
    assert entry.resource_id is None
    assert entry.details == {}
    assert persisted_values["actor_id"] is None
    assert persisted_values["resource_id"] is None
    assert persisted_values["details"] == {}