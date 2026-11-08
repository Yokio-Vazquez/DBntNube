"""Client helper for authenticated event API tests."""
import os
import secrets

from fastapi.testclient import TestClient

from src.database import get_db_writer


class MemoryAuditSession:
    """Keep unit tests independent from PostgreSQL."""

    def __init__(self):
        self.pending = []
        self.persisted = []

    def execute(self, statement):
        self.pending.append(statement.compile().params)

    def commit(self):
        self.persisted.extend(self.pending)
        self.pending.clear()


class ReaderClient(TestClient):
    def __init__(
        self,
        app,
        *,
        audit_session=None,
        persist_audit=False,
        **kwargs,
    ):
        token = os.environ.setdefault(
            "EVENTS_READER_TOKEN", secrets.token_urlsafe(32)
        )
        self.audit_session = audit_session or MemoryAuditSession()
        if not persist_audit:
            def override_audit_session():
                yield self.audit_session

            app.dependency_overrides[get_db_writer] = override_audit_session
        super().__init__(
            app,
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
