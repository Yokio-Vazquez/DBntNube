"""
test_m06_recovery.py — Pruebas de Persona 3: simulacion de fallo y recuperacion desde fixture.

Casos:
- Normal: Recuperacion completa desde fixture retorna el numero correcto de registros.
- Limite 1: El fixture existe, no esta vacio y contiene el esquema y campos obligatorios.
- Limite 2: Umbrales frontera de verificacion de restauracion y desastre sobre tabla vacia.
- Fallo declarado: Simular que DynamoDB esta caido durante la recuperacion produce un fallo real (BotoCoreError).
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
# ---------------------------------------------------------------------------
# Caso Limite 1: El fixture debe existir y tener items validos
# ---------------------------------------------------------------------------
def test_m06_fixture_file_exists_and_is_valid():
    """
    Limite 1: El archivo de fixture debe existir en la ruta esperada
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
# Caso Limite 2: Comportamiento de limites y frontera en verificacion y desastre
# ---------------------------------------------------------------------------
def test_m06_verify_restore_boundary_conditions():
    """
    Limite 2: Valida los umbrales frontera de la verificacion de restauracion
    y el comportamiento de simulacion de desastre cuando la tabla ya esta vacia:
    - Conteo exacto: actual == expected -> True (restauracion completa)
    - Conteo superior: actual > expected -> True (cumple con el minimo)
    - Conteo deficitario: actual < expected -> False (restauracion incompleta detectada)
    - Limite inferior: expected == 0 con tabla vacia -> True
    - Desastre sobre tabla vacia: retorna 0 items eliminados sin fallar
    """
    from scripts.disaster_recovery import simulate_disaster, verify_restore

    mock_table = MagicMock()

    # Frontera 1: conteo exacto de registros restaurados
    mock_table.scan.return_value = {"Count": 5}
    assert verify_restore(mock_table, expected_count=5) is True

    # Frontera 2: conteo superior al esperado
    mock_table.scan.return_value = {"Count": 10}
    assert verify_restore(mock_table, expected_count=5) is True

    # Frontera 3: conteo deficitario (falta 1 registro para cumplir)
    mock_table.scan.return_value = {"Count": 4}
    assert verify_restore(mock_table, expected_count=5) is False

    # Frontera 4: cero registros esperados en tabla vacia
    mock_table.scan.return_value = {"Count": 0}
    assert verify_restore(mock_table, expected_count=0) is True

    # Frontera 5: simular desastre sobre tabla previamente vacia
    mock_empty_table = MagicMock()
    mock_empty_table.scan.return_value = {"Items": []}
    deleted = simulate_disaster(mock_empty_table)
    assert deleted == 0


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

