"""Cliente de los escenarios históricos que ejercen lectura autorizada."""
import secrets
import os

from fastapi.testclient import TestClient


class ReaderClient(TestClient):
    def __init__(self, app):
        token = os.environ.setdefault("EVENTS_READER_TOKEN", secrets.token_urlsafe(32))
        super().__init__(app, headers={"Authorization": f"Bearer {token}"})
