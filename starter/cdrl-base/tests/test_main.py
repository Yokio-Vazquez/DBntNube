import pytest
from fastapi.testclient import TestClient
from src.main import app
import uuid
from datetime import datetime, timezone

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200

def test_create_metric_success():
    payload = {
        "external_id": f"test-metric-{uuid.uuid4()}",
        "game_id": 1,
        "metric_name": "duration",
        "metric_value": 50.5,
        "unit": "hours",
        "measured_at": datetime.now(timezone.utc).isoformat()
    }
    response = client.post("/metrics", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "success"

def test_create_metric_duplicate_external_id():
    unique_ext_id = f"test-metric-{uuid.uuid4()}"
    payload = {
        "external_id": unique_ext_id,
        "game_id": 1,
        "metric_name": "rating",
        "metric_value": 4.5,
        "unit": "stars",
        "measured_at": datetime.now(timezone.utc).isoformat()
    }
    # Primera vez exitosa
    response1 = client.post("/metrics", json=payload)
    assert response1.status_code == 201
    
    # Segunda vez debe fallar por external_id duplicado
    response2 = client.post("/metrics", json=payload)
    assert response2.status_code == 409
    assert "Conflict" in response2.json()["detail"]

def test_create_metric_invalid_game_id():
    payload = {
        "external_id": f"test-metric-{uuid.uuid4()}",
        "game_id": 99999,
        "metric_name": "rating",
        "metric_value": 4.5,
        "unit": "stars",
        "measured_at": datetime.now(timezone.utc).isoformat()
    }
    response = client.post("/metrics", json=payload)
    assert response.status_code == 422
    assert "no existe" in response.json()["detail"].lower()

def test_create_metric_invalid_constraint():
    payload = {
        "external_id": f"test-metric-{uuid.uuid4()}",
        "game_id": 1,
        "metric_name": "duration",
        "metric_value": -10,  # duración inválida (menor a 0)
        "unit": "hours",
        "measured_at": datetime.now(timezone.utc).isoformat()
    }
    response = client.post("/metrics", json=payload)
    assert response.status_code == 422
    assert "restricción" in response.json()["detail"].lower() or "constraint" in response.json()["detail"].lower()
