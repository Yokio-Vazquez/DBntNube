"""
test_event_access.py — Pruebas de acceso y controles por colección (Persona 3).

Verifica la matriz de autorización por colección y operación (ADR-009) y el contrato
de auditoría de Persona 2 en los cuatro casos exigidos:
1. Caso Normal: creación por escritor (201) y consulta por lector (200 en /events y /events/page).
2. Límite 1 (Lectura): consulta no autenticada rechazada con 401, sin revelar contenido.
3. Límite 2 (Escritura): creación intentada por lector rechazada con 403; documento permanece ausente.
4. Fallo Declarado: colisión de credenciales lector/escritor falla de forma cerrada con 401.

Además, verifica que los registros de auditoría cumplen con los 4 campos obligatorios
(actor_id, action, resource_type, outcome) y que ningún marcador sintético sensible se filtre.
"""
import secrets
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src import main
from src.database import get_db_writer


class AuditSession:
    def __init__(self):
        self.pending = []
        self.persisted = []

    def execute(self, statement):
        table_name = getattr(getattr(statement, "table", None), "name", "unknown")
        params = statement.compile().params
        self.pending.append({"_table": table_name, **params})
        return SimpleNamespace(rowcount=1)

    def commit(self):
        self.persisted.extend(self.pending)
        self.pending.clear()

    def rollback(self):
        self.pending.clear()


class StorageFixture:
    def __init__(self):
        self.events = {}

    def query_events(self, game_id: int):
        return [doc for doc in self.events.values() if doc.get("game_id") == game_id]

    def query_events_page(self, game_id: int, limit: int = 25, cursor: str | None = None):
        items = self.query_events(game_id)
        return {
            "items": items[:limit],
            "nextCursor": None,
            "limit": limit,
            "order": "occurred_at_desc",
        }

    def create_event(self, event, audit_operation_id: str | None = None):
        key = (event.game_id, event.event_key)
        if key in self.events:
            return False
        doc = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        if audit_operation_id:
            doc["_audit_operation_id"] = audit_operation_id
        self.events[key] = doc
        return True


def make_synthetic_event(game_id: int, event_key: str) -> dict:
    payload = {
        "game_id": game_id,
        "event_key": event_key,
        "event_type": "m09_synthetic_test",
        "occurred_at": "2026-11-08T18:00:00Z",
        "source": "m09-persona3-test",
    }
    if main.EventDocument.model_fields.get("schema_version") and main.EventDocument.model_fields["schema_version"].default == 3:
        payload["platform"] = "pc"
        payload["metadata"] = {"fixture": True}
    return payload


def setup_test_context(monkeypatch):
    reader = f"token-reader-{secrets.token_urlsafe(16)}"
    writer = f"token-writer-{secrets.token_urlsafe(16)}"
    monkeypatch.setenv("EVENTS_READER_TOKEN", reader)
    monkeypatch.setenv("EVENTS_WRITER_TOKEN", writer)

    storage = StorageFixture()
    monkeypatch.setattr(main, "query_events", storage.query_events)
    monkeypatch.setattr(main, "query_events_page", storage.query_events_page)
    monkeypatch.setattr(main, "create_event", storage.create_event)

    session = AuditSession()

    def override_session():
        yield session

    previous_override = main.app.dependency_overrides.get(get_db_writer)
    monkeypatch.setitem(main.app.dependency_overrides, get_db_writer, override_session)

    client = TestClient(main.app)

    def restore():
        if previous_override is None:
            main.app.dependency_overrides.pop(get_db_writer, None)
        else:
            main.app.dependency_overrides[get_db_writer] = previous_override

    return client, session, storage, reader, writer, restore


def get_audit_records(session):
    return [
        row for row in session.persisted
        if row.get("resource_type") == "events"
    ]


# ── Casos de prueba de Persona 3 ──────────────────────────────────────────────

def test_normal_case_writer_create_reader_query(monkeypatch):
    """Caso Normal: Escritor crea evento con clave única (201) y lector lo consulta (200 en /events y /events/page)."""
    client, session, storage, reader, writer, restore = setup_test_context(monkeypatch)
    try:
        game_id = 911
        event_key = f"m09-normal-{secrets.token_hex(4)}"
        event = make_synthetic_event(game_id, event_key)

        # 1. Escritor crea el evento
        res_post = client.post(
            "/events",
            json=event,
            headers={"Authorization": f"Bearer {writer}"},
        )
        assert res_post.status_code == 201, res_post.text
        assert (game_id, event_key) in storage.events

        # 2. Lector consulta /events
        res_get = client.get(
            f"/events?game_id={game_id}",
            headers={"Authorization": f"Bearer {reader}"},
        )
        assert res_get.status_code == 200, res_get.text
        items = res_get.json()
        assert any(it.get("event_key") == event_key for it in items)

        # 3. Lector consulta /events/page
        res_page = client.get(
            f"/events/page?game_id={game_id}&limit=10",
            headers={"Authorization": f"Bearer {reader}"},
        )
        assert res_page.status_code == 200, res_page.text
        page_items = res_page.json().get("items", [])
        assert any(it.get("event_key") == event_key for it in page_items)

        # 4. Verificación de auditoría: 3 registros de éxito
        audits = get_audit_records(session)
        assert len(audits) == 3
        # POST create
        assert audits[0]["actor_id"] == "writer"
        assert audits[0]["action"] == "create"
        assert audits[0]["outcome"] == "success"
        # GET read
        assert audits[1]["actor_id"] == "reader"
        assert audits[1]["action"] == "read"
        assert audits[1]["outcome"] == "success"
        # GET page read
        assert audits[2]["actor_id"] == "reader"
        assert audits[2]["action"] == "read"
        assert audits[2]["outcome"] == "success"
    finally:
        restore()


def test_boundary_read_unauthenticated_omits_content(monkeypatch):
    """Límite 1 (Lectura): Consulta no autenticada rechaza con 401 y omite contenido."""
    client, session, storage, reader, writer, restore = setup_test_context(monkeypatch)
    try:
        game_id = 912
        event_key = f"m09-secret-doc-{secrets.token_hex(4)}"
        event = make_synthetic_event(game_id, event_key)
        storage.events[(game_id, event_key)] = event

        # Consultar /events sin credencial
        res_get = client.get(f"/events?game_id={game_id}")
        assert res_get.status_code == 401
        assert event_key not in res_get.text
        assert "m09_synthetic_test" not in res_get.text

        # Consultar /events/page sin credencial
        res_page = client.get(f"/events/page?game_id={game_id}")
        assert res_page.status_code == 401
        assert event_key not in res_page.text

        # Verificación de auditoría: 2 registros denegados
        audits = get_audit_records(session)
        assert len(audits) == 2
        for row in audits:
            assert row["actor_id"] == "anonymous"
            assert row["action"] == "read"
            assert row["outcome"] == "denied"
            assert row["resource_type"] == "events"
    finally:
        restore()


def test_boundary_write_reader_attempt_denied(monkeypatch):
    """Límite 2 (Escritura): Lector intenta crear evento y recibe 403; documento permanece ausente."""
    client, session, storage, reader, writer, restore = setup_test_context(monkeypatch)
    try:
        game_id = 913
        event_key = f"m09-forbidden-{secrets.token_hex(4)}"
        event = make_synthetic_event(game_id, event_key)

        # Lector intenta POST /events
        res_post = client.post(
            "/events",
            json=event,
            headers={"Authorization": f"Bearer {reader}"},
        )
        assert res_post.status_code == 403
        assert (game_id, event_key) not in storage.events

        # Consulta posterior autorizada confirma ausencia
        res_check = client.get(
            f"/events?game_id={game_id}",
            headers={"Authorization": f"Bearer {reader}"},
        )
        assert res_check.status_code == 200
        assert not any(it.get("event_key") == event_key for it in res_check.json())

        # Verificación de auditoría
        audits = get_audit_records(session)
        assert len(audits) == 2
        assert audits[0]["actor_id"] == "reader"
        assert audits[0]["action"] == "create"
        assert audits[0]["outcome"] == "denied"
        assert audits[0]["resource_type"] == "events"
    finally:
        restore()


def test_declared_failure_colliding_credentials_fail_closed(monkeypatch):
    """Fallo declarado: Lector y escritor comparten la misma credencial sintética; la política deniega con 401."""
    client, session, storage, reader, writer, restore = setup_test_context(monkeypatch)
    try:
        colliding_token = "shared-secret-token-collision"
        monkeypatch.setenv("EVENTS_READER_TOKEN", colliding_token)
        monkeypatch.setenv("EVENTS_WRITER_TOKEN", colliding_token)

        game_id = 914
        event_key = f"m09-collision-{secrets.token_hex(4)}"
        event = make_synthetic_event(game_id, event_key)

        # Intento de creación con la credencial compartida/colisionada
        res_post = client.post(
            "/events",
            json=event,
            headers={"Authorization": f"Bearer {colliding_token}"},
        )
        assert res_post.status_code == 401
        assert (game_id, event_key) not in storage.events

        # Verificación de auditoría
        audits = get_audit_records(session)
        assert len(audits) == 1
        assert audits[0]["actor_id"] == "anonymous"
        assert audits[0]["action"] == "create"
        assert audits[0]["outcome"] == "denied"
        assert audits[0]["resource_type"] == "events"
    finally:
        restore()


def test_audit_mandatory_fields_and_sensitive_marker_exclusion(monkeypatch):
    """Comprueba los 4 campos obligatorios y que los marcadores sensibles no aparezcan en registros de auditoría."""
    client, session, storage, reader, writer, restore = setup_test_context(monkeypatch)
    marker = f"SECRET_SENSITIVE_MARKER_{secrets.token_hex(8)}"
    try:
        game_id = 915
        event_key = f"m09-marker-test-{secrets.token_hex(4)}"
        event = make_synthetic_event(game_id, event_key)

        # Petición autorizada con cabecera sensible
        res = client.post(
            "/events",
            json=event,
            headers={
                "Authorization": f"Bearer {writer}",
                "X-Sensitive-Custom-Marker": marker,
            },
        )
        assert res.status_code == 201

        # Petición denegada con cabecera sensible
        res_denied = client.post(
            "/events",
            json=make_synthetic_event(game_id, "denied-key"),
            headers={
                "Authorization": f"Bearer {reader}",
                "X-Sensitive-Custom-Marker": marker,
            },
        )
        assert res_denied.status_code == 403

        # Revisar todas las filas de auditoría persistidas
        audits = get_audit_records(session)
        assert len(audits) >= 2
        for row in audits:
            # 4 campos obligatorios
            assert "actor_id" in row and row["actor_id"] in {"writer", "reader", "anonymous"}
            assert "action" in row and row["action"] in {"create", "read"}
            assert "resource_type" in row and row["resource_type"] == "events"
            assert "outcome" in row and row["outcome"] in {"success", "denied", "conflict", "unavailable", "failure"}
            # Ausencia total del marcador sensible en la fila
            assert marker not in str(row)
    finally:
        restore()


def test_remediation_reader_create_denial_recorded(monkeypatch):
    """Prueba de regresión de Persona 2: verificación de que la denegación al lector se audita debidamente."""
    client, session, storage, reader, writer, restore = setup_test_context(monkeypatch)
    try:
        game_id = 916
        event = make_synthetic_event(game_id, "remediation-key")
        res = client.post(
            "/events",
            json=event,
            headers={"Authorization": f"Bearer {reader}"},
        )
        assert res.status_code == 403
        audits = get_audit_records(session)
        assert len(audits) == 1
        assert audits[0]["actor_id"] == "reader"
        assert audits[0]["action"] == "create"
        assert audits[0]["outcome"] == "denied"
    finally:
        restore()


def test_event_permissions(monkeypatch):
    """Prueba base de permisos del hito M09."""
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
