"""
test_m06_recovery.py — Pruebas de Persona 3: simulacion de fallo y recuperacion desde fixture.

Casos:
- Normal: Recuperacion completa desde fixture retorna el numero correcto de registros.
- Failure: Simular que DynamoDB esta caido durante la recuperacion produce un fallo real.
"""
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "recovery_fixture.json"


def _load_fixture():
    """Lee el fixture de recuperacion y retorna la lista de items."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["items"]


# ---------------------------------------------------------------------------
# Caso Normal: Recuperacion exitosa desde fixture
# ---------------------------------------------------------------------------
def test_m06_recovery_restores_correct_number_of_records():
    """
    Fallo declarado / Recuperacion:
    Simula que la tabla esta vacia (desastre) y restaura desde el fixture.
    Verifica que la cantidad de registros recuperados coincide con el fixture.
    """
    fixture_items = _load_fixture()
    expected_count = len(fixture_items)

    # Mock de la tabla DynamoDB
    mock_resource = MagicMock()
    mock_table = MagicMock()
    mock_resource.Table.return_value = mock_table

    # Simular scan vacio (tabla borrada por "desastre")
    mock_table.scan.return_value = {"Items": [], "Count": expected_count}

    # Simular batch_writer como context manager
    mock_batch = MagicMock()
    mock_table.batch_writer.return_value.__enter__ = MagicMock(return_value=mock_batch)
    mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

    with patch("src.nosql.dynamodb_resource", return_value=mock_resource):
        from scripts.disaster_recovery import restore_from_fixture, verify_restore

        t0 = time.perf_counter()
        restored = restore_from_fixture(mock_table, FIXTURE_PATH)
        elapsed = time.perf_counter() - t0

        verified = verify_restore(mock_table, restored)

    assert restored == expected_count, (
        f"Se esperaban {expected_count} registros recuperados, se obtuvieron {restored}"
    )
    assert verified is True, "La verificacion de recuperacion debe pasar"
    assert elapsed < 5.0, "La recuperacion debe completarse en menos de 5 segundos"
    print(
        f"\n[RECOVERY] {restored} registros restaurados en {elapsed:.4f}s — verificacion: OK"
    )


# ---------------------------------------------------------------------------
# Caso Limite: El fixture debe existir y tener items validos
# ---------------------------------------------------------------------------
def test_m06_fixture_file_exists_and_is_valid():
    """
    Limite: El archivo de fixture debe existir en la ruta esperada
    y contener al menos un item con los campos obligatorios.
    """
    assert FIXTURE_PATH.is_file(), f"El fixture no existe en {FIXTURE_PATH}"

    items = _load_fixture()
    assert len(items) > 0, "El fixture debe tener al menos un item"

    required_fields = {"game_id", "event_key", "event_type", "occurred_at", "source"}
    for item in items:
        missing = required_fields - set(item.keys())
        assert not missing, f"Item del fixture tiene campos faltantes: {missing} — item: {item}"


# ---------------------------------------------------------------------------
# Fallo declarado: DynamoDB inaccesible durante la recuperacion
# ---------------------------------------------------------------------------
def test_m06_recovery_fails_when_dynamodb_unreachable():
    """
    Fallo declarado: Si DynamoDB esta inaccesible durante la recuperacion,
    la excepcion BotoCoreError debe propagarse como fallo real de prueba.
    NO se omite (skip) este caso.
    """
    mock_resource = MagicMock()
    mock_table = MagicMock()
    mock_resource.Table.return_value = mock_table

    # Simular que batch_writer lanza BotoCoreError
    mock_table.batch_writer.side_effect = BotoCoreError()

    with patch("src.nosql.dynamodb_resource", return_value=mock_resource):
        from scripts.disaster_recovery import restore_from_fixture

        with pytest.raises(BotoCoreError):
            restore_from_fixture(mock_table, FIXTURE_PATH)
