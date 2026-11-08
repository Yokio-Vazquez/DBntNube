"""Client helper for authenticated event API tests."""
import os
import secrets
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from src.database import get_db_writer

_NO_OVERRIDE = object()


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
        self.persist_audit = persist_audit
        self.test_app = app
        super().__init__(
            app,
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )

    def request(self, method, url, *args, **kwargs):
        path = urlsplit(str(url)).path
        if self.persist_audit or not path.startswith("/events"):
            return super().request(method, url, *args, **kwargs)

        overrides = self.test_app.dependency_overrides
        previous_override = overrides.get(get_db_writer, _NO_OVERRIDE)
        if previous_override is not _NO_OVERRIDE:
            return super().request(method, url, *args, **kwargs)

        def override_audit_session():
            yield self.audit_session

        overrides[get_db_writer] = override_audit_session
        try:
            return super().request(method, url, *args, **kwargs)
        finally:
            overrides.pop(get_db_writer, None)
