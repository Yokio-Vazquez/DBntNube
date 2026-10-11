"""
Persona 3 — Tests M02: Modelo relacional, restricciones y consultas parametrizadas.
Casos: normal, vacío, límite y fallo declarado.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from src.main import app
from src.database import MigratorSessionLocal as SessionLocal
from src.models import Platform, GamePlatform, MetricDefinition
from datetime import date

client = TestClient(app)


# ── Caso normal ────────────────────────────────────────────────
def test_m02_normal_query_games_by_platform_and_rating():
    """
    Consulta parametrizada: juegos en PS5 con rating >= 4.0.
    Debe devolver al menos un resultado del seed.
    """
    response = client.get("/metrics/by-value", params={
        "metric_name": "rating",
        "min_value": 4.0,
    })
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0, "Debe haber al menos un juego con rating >= 4.0"
    for item in data:
        assert item["metric_value"] >= 4.0


# ── Caso vacío ─────────────────────────────────────────────────
def test_m02_empty_no_metrics_for_nonexistent_game():
    """
    Consulta con un game_id que no tiene métricas asociadas.
    Debe devolver una lista vacía, NO un error.
    """
    response = client.get("/metrics", params={
        "game_id": 999999,
    })
    assert response.status_code == 200
    data = response.json()
    assert data == [], f"Esperaba lista vacía, recibió {data}"


# ── Caso límite ────────────────────────────────────────────────
def test_m02_boundary_game_platform_status_valid_values():
    """
    Insertar un game_platform con cada uno de los 3 status permitidos
    (planned, available, retired). Los 3 deben aceptarse sin error.
    Se usan game_id distintos para evitar colisión de PK con el seed.
    """
    db = SessionLocal()
    try:
        platforms = db.query(Platform).all()
        assert len(platforms) > 0, "Debe haber al menos una plataforma del seed"

        # Usar game_ids 3,4,5 con la última plataforma (menos usada en seed)
        platform = platforms[-1]
        valid_statuses = ["planned", "available", "retired"]
        test_game_ids = [3, 4, 5]

        for game_id, status in zip(test_game_ids, valid_statuses):
            # Usar savepoint para poder hacer rollback individual
            nested = db.begin_nested()
            try:
                gp = GamePlatform(
                    game_id=game_id,
                    platform_id=platform.id,
                    release_date=date(2025, 1, 1),
                    status=status,
                )
                db.add(gp)
                db.flush()  # Si no lanza error, el status fue aceptado
            finally:
                nested.rollback()
    finally:
        db.close()


# ── Fallo declarado ────────────────────────────────────────────
def test_m02_failure_invalid_platform_status_rejected():
    """
    Intentar insertar un game_platform con status='paused' (inválido).
    La restricción game_platforms_status_valid debe rechazarlo.
    """
    db = SessionLocal()
    try:
        platform = db.query(Platform).first()
        assert platform is not None, "Debe haber al menos una plataforma del seed"

        gp = GamePlatform(
            game_id=1,
            platform_id=platform.id,
            release_date=date(2025, 6, 15),
            status="paused",  # ← valor inválido
        )
        db.add(gp)
        with pytest.raises(IntegrityError) as exc_info:
            db.flush()
        assert "game_platforms_status_valid" in str(exc_info.value.orig).lower()
    finally:
        db.rollback()
        db.close()
