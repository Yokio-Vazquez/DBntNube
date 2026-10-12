import pytest
from fastapi.testclient import TestClient
from botocore.exceptions import BotoCoreError

from src.main import app

client = TestClient(app)

# ── Caso Normal ─────────────────────────────────────────────────
def test_m04_normal_query_events_by_game(monkeypatch):
    """
    Prueba normal: Consultar eventos para un game_id que tiene datos (fixtures).
    Usa monkeypatch para que no dependa de que DynamoDB esté corriendo.
    Debe retornar 200 OK y una lista con los eventos.
    """
    import src.main as main_module

    expected = [
        {
            "game_id": 1,
            "event_key": "session_started#2026-09-27T10:00:00Z#fixture-001",
            "event_type": "session_started",
            "occurred_at": "2026-09-27T10:00:00Z",
            "source": "synthetic-fixture",
            "schemaVersion": 1,
        }
    ]
    monkeypatch.setattr(main_module, "query_events", lambda game_id: expected)

    response = client.get("/events?game_id=1")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["game_id"] == 1


# ── Casos Límite ────────────────────────────────────────────────
def test_m04_boundary_query_events_no_results(monkeypatch):
    """
    Caso límite 1: Consultar eventos para un game_id válido pero sin datos.
    Debe retornar 200 OK y una lista vacía.
    """
    import src.main as main_module
    monkeypatch.setattr(main_module, "query_events", lambda game_id: [])

    response = client.get("/events?game_id=999999")
    assert response.status_code == 200
    data = response.json()
    assert data == []


def test_m04_boundary_query_events_invalid_game_id():
    """
    Caso límite 2: Consultar con un game_id inválido (menor a 1).
    Debe ser bloqueado por la validación de FastAPI (422 Unprocessable Entity).
    """
    response = client.get("/events?game_id=0")
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data


# ── Fallo Declarado ─────────────────────────────────────────────
def test_m04_failure_dynamodb_unreachable(monkeypatch):
    """
    Fallo declarado: Simular que DynamoDB se cae o es inaccesible.
    La API debe manejar la excepción de botocore y retornar 503 Service Unavailable.
    NO se omite (skip) este caso: un servicio caído DEBE producir fallo real.
    """
    def mock_query_events(*args, **kwargs):
        raise BotoCoreError()

    monkeypatch.setattr("src.main.query_events", mock_query_events)

    response = client.get("/events?game_id=1")
    assert response.status_code == 503
    data = response.json()
    assert "detail" in data
    assert "Service Unavailable" in data["detail"]
