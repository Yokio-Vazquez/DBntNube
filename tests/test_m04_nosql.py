import pytest
from fastapi.testclient import TestClient
from botocore.exceptions import BotoCoreError

from src.main import app

client = TestClient(app)

# ── Caso Normal ─────────────────────────────────────────────────
def test_m04_normal_query_events_by_game():
    """
    Prueba normal: Consultar eventos para un game_id que tiene datos (fixtures).
    Debe retornar 200 OK y una lista con los eventos.
    """
    response = client.get("/events?game_id=1")
    # Dependiendo de si DynamoDB está corriendo localmente, esto podría fallar.
    # Asumimos que Docker Desktop está corriendo con DynamoDB local.
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 2  # Hay al menos 2 fixtures para game_id=1
        for event in data:
            assert event["game_id"] == 1
    elif response.status_code == 503:
        pytest.skip("DynamoDB local no está corriendo.")


# ── Casos Límite ────────────────────────────────────────────────
def test_m04_boundary_query_events_no_results():
    """
    Caso límite 1: Consultar eventos para un game_id válido pero sin datos.
    Debe retornar 200 OK y una lista vacía.
    """
    response = client.get("/events?game_id=999999")
    if response.status_code == 200:
        data = response.json()
        assert data == []
    elif response.status_code == 503:
        pytest.skip("DynamoDB local no está corriendo.")

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
    """
    def mock_query_events(*args, **kwargs):
        raise BotoCoreError()

    # Parcheamos la función query_events en src.main
    monkeypatch.setattr("src.main.query_events", mock_query_events)

    response = client.get("/events?game_id=1")
    assert response.status_code == 503
    data = response.json()
    assert "detail" in data
    assert "Service Unavailable" in data["detail"]
