"""
test_m07_document_evolution.py — Pruebas de integración M07 (Persona 3).

Se ejecutan contra DynamoDB Local REAL (sin mocks de tabla) en una tabla
exclusiva derivada de DYNAMODB_TABLE_M07_TEST con sufijo único; nunca usan
cdrl_events. Cada prueba crea la tabla con la misma llave e índice que
cdrl_events y la elimina en el teardown, incluso si la prueba falla.
Si DynamoDB no está disponible las pruebas FALLAN (no se omiten).

| Tipo            | Prueba                                                    |
|-----------------|-----------------------------------------------------------|
| Normal          | test_normal_migration_of_fixture                          |
| Límite 1        | test_boundary_second_migration_is_noop                    |
| Límite 2        | test_boundary_empty_table                                 |
| Límite 3        | test_boundary_dry_run_never_writes                        |
| Rollback        | test_rollback_restores_exact_initial_snapshot             |
| Rollback global | test_rollback_restores_previously_migrated_v3_to_v2       |
| Fallo declarado | test_declared_failure_invalid_document_exit_code_2        |
| Compat API      | test_api_reads_migrated_documents_and_projections         |
"""
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import scripts.migrate_events as migration
import src.nosql as nosql
from scripts.m07_demo import (
    create_isolated_table,
    drop_table,
    fixture_items,
    isolated_table_name,
    load_items,
    run_cli,
    scan_all,
    unique_suffix,
)
from src.event_schemas import normalize_event, upcast_to_v3
from src.main import app

NATIVE_KEY = "m07-v3-native"
INVALID_KEY = "m07-invalid"
LEGACY_KEYS = {"m07-v1-001", "m07-v1-002", "m07-v2-001", "m07-v2-002"}


def by_key(items):
    return {item["event_key"]: item for item in items}


@pytest.fixture
def m07_table():
    """Tabla exclusiva vacía; se elimina al final aunque la prueba falle."""
    name = isolated_table_name(unique_suffix())
    assert name not in {nosql.TABLE_NAME, "cdrl_events"}
    table = create_isolated_table(name)
    try:
        yield table
    finally:
        drop_table(name)


@pytest.fixture
def loaded_table(m07_table):
    load_items(m07_table, fixture_items())
    return m07_table


def test_isolated_table_mirrors_events_schema(m07_table):
    description = m07_table.meta.client.describe_table(TableName=m07_table.name)["Table"]
    assert description["KeySchema"] == nosql.TABLE_KEY_SCHEMA
    assert [index["IndexName"] for index in description["GlobalSecondaryIndexes"]] == [
        nosql.EVENT_TYPE_INDEX
    ]


def test_isolated_table_name_rejects_shared_table(monkeypatch):
    monkeypatch.setenv("DYNAMODB_TABLE_M07_TEST", "cdrl_events")
    with pytest.raises(ValueError):
        isolated_table_name()


# ── Normal ──────────────────────────────────────────────────────────────────
def test_normal_migration_of_fixture(loaded_table):
    before = by_key(scan_all(loaded_table))

    result = migration.migrate_table(loaded_table)

    assert (result["scanned"], result["migrated"], result["skipped"]) == (6, 4, 1)
    assert [failure["event_key"] for failure in result["failed"]] == [INVALID_KEY]
    after = by_key(scan_all(loaded_table))
    for key in LEGACY_KEYS:
        assert after[key]["schemaVersion"] == 3
        assert after[key]["platform"] == "unknown"
        assert after[key]["metadata"] == {}
        assert after[key]["migratedFrom"] in (1, 2)
        assert normalize_event(after[key]).schema_version == 3
    # Los atributos adicionales originales se conservan.
    assert after["m07-v1-002"]["custom"] == before["m07-v1-002"]["custom"]
    assert after["m07-v2-002"]["custom"] == before["m07-v2-002"]["custom"]
    # v3 nativo omitido e inválido intacto.
    assert after[NATIVE_KEY] == before[NATIVE_KEY]
    assert after[INVALID_KEY] == before[INVALID_KEY]


# ── Límite 1: repetible ─────────────────────────────────────────────────────
def test_boundary_second_migration_is_noop(loaded_table):
    migration.migrate_table(loaded_table)
    after_first = scan_all(loaded_table)

    second = migration.migrate_table(loaded_table)

    assert second["migrated"] == 0
    assert second["skipped"] == 5
    assert len(second["failed"]) == 1
    assert scan_all(loaded_table) == after_first


# ── Límite 2: tabla vacía ───────────────────────────────────────────────────
def test_boundary_empty_table(m07_table):
    migrated = migration.migrate_table(m07_table)
    rolled_back = migration.rollback_table(m07_table)

    assert (migrated["scanned"], migrated["migrated"], migrated["skipped"], migrated["failed"]) == (0, 0, 0, [])
    assert (rolled_back["scanned"], rolled_back["rolledBack"], rolled_back["skipped"], rolled_back["failed"]) == (
        0, 0, 0, [],
    )
    assert scan_all(m07_table) == []


# ── Límite 3: dry-run ───────────────────────────────────────────────────────
def test_boundary_dry_run_never_writes(loaded_table, tmp_path):
    before = scan_all(loaded_table)
    report = tmp_path / "dry-run.json"
    args = ["--table", loaded_table.name, "--report", str(report), "--dry-run"]

    assert run_cli(args) == 2
    assert scan_all(loaded_table) == before
    migration.migrate_table(loaded_table)
    migrated = scan_all(loaded_table)
    assert run_cli(["--rollback", *args]) == 2
    assert scan_all(loaded_table) == migrated

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert [run["dryRun"] for run in payload["runs"]] == [True, True]
    assert payload["runs"][0]["migrated"] == 4
    assert payload["runs"][1]["rolledBack"] == 4
    # Una simulación nunca demuestra idempotencia ni rollback.
    assert payload["idempotent"] is False
    assert payload["rollbackVerified"] is False


# ── Rollback ────────────────────────────────────────────────────────────────
def test_rollback_restores_exact_initial_snapshot(loaded_table):
    initial = scan_all(loaded_table)

    migration.migrate_table(loaded_table)
    result = migration.rollback_table(loaded_table)

    assert result["rolledBack"] == 4
    assert result["skipped"] == 1
    assert [failure["event_key"] for failure in result["failed"]] == [INVALID_KEY]
    restored = scan_all(loaded_table)
    assert restored == initial
    restored_by_key = by_key(restored)
    # v1 implícita sin schemaVersion, v1 explícita con schemaVersion=1.
    assert "schemaVersion" not in restored_by_key["m07-v1-001"]
    assert restored_by_key["m07-v1-002"]["schemaVersion"] == 1
    assert not {"migratedFrom", "migratedVersionExplicit", "platform"} & set(restored_by_key["m07-v1-001"])
    # v3 nativo sigue en v3 e inválido nunca cambió.
    assert restored_by_key[NATIVE_KEY]["schemaVersion"] == 3
    assert "migratedFrom" not in restored_by_key[NATIVE_KEY]
    assert restored_by_key[INVALID_KEY]["schemaVersion"] == 99


def test_rollback_restores_previously_migrated_v3_to_v2(m07_table):
    original = {
        "game_id": 4,
        "event_key": "m07-previously-migrated",
        "event_type": "session_started",
        "occurred_at": "2026-10-25T10:07:00Z",
        "source": "synthetic-fixture",
        "schemaVersion": 2,
    }
    load_items(m07_table, [upcast_to_v3(original)])

    result = migration.rollback_table(m07_table)

    assert result["rolledBack"] == 1
    assert scan_all(m07_table) == [original]


# ── Fallo declarado ─────────────────────────────────────────────────────────
def test_declared_failure_invalid_document_exit_code_2(loaded_table, tmp_path):
    invalid_before = deepcopy(by_key(scan_all(loaded_table))[INVALID_KEY])
    report = tmp_path / "failure.json"

    exit_code = run_cli(["--table", loaded_table.name, "--report", str(report)])

    assert exit_code == 2
    assert by_key(scan_all(loaded_table))[INVALID_KEY] == invalid_before
    run = json.loads(report.read_text(encoding="utf-8"))["runs"][0]
    assert run["failed"] == 1
    assert run["failureDetails"][0]["event_key"] == INVALID_KEY
    assert "99" in run["failureDetails"][0]["reason"]


def test_cli_returns_zero_without_invalid_documents(m07_table, tmp_path):
    valid = [item for item in fixture_items() if item["event_key"] != INVALID_KEY]
    load_items(m07_table, valid)

    assert run_cli(["--table", m07_table.name, "--report", str(tmp_path / "ok.json")]) == 0


# ── Compatibilidad del API ──────────────────────────────────────────────────
def test_api_reads_migrated_documents_and_projections(loaded_table, monkeypatch):
    monkeypatch.setattr(nosql, "TABLE_NAME", loaded_table.name)
    migration.migrate_table(loaded_table)

    with TestClient(app) as client:
        default = client.get("/events", params={"game_id": 1})
        v1 = client.get("/events", params={"game_id": 1, "version": 1})
        v2 = client.get("/events", params={"game_id": 2, "version": 2})
        v3 = client.get("/events", params={"game_id": 2, "version": 3})
        invalid_target = client.get("/events", params={"game_id": 1, "version": 9})
        unknown_stored = client.get("/events", params={"game_id": 3})

    assert default.status_code == 200
    events = by_key(default.json())
    assert set(events) == {"m07-v1-001", "m07-v1-002", "m07-v2-001"}
    assert all(event["schemaVersion"] == 3 and event["platform"] == "unknown" for event in events.values())
    assert all("migratedVersionExplicit" not in event for event in events.values())

    assert v1.status_code == 200
    assert all(event["schemaVersion"] == 1 for event in v1.json())
    assert all(not {"platform", "metadata", "migratedFrom"} & set(event) for event in v1.json())

    assert v2.status_code == 200
    v2_events = by_key(v2.json())
    assert all(event["schemaVersion"] == 2 for event in v2_events.values())
    assert all(not {"platform", "metadata", "migratedFrom"} & set(event) for event in v2_events.values())
    # La proyección no modifica almacenamiento: el v3 nativo sigue en v3.
    assert by_key(scan_all(loaded_table))[NATIVE_KEY]["schemaVersion"] == 3

    assert v3.status_code == 200
    v3_events = by_key(v3.json())
    assert v3_events[NATIVE_KEY]["platform"] == "pc"
    assert v3_events[NATIVE_KEY]["metadata"] == {"synthetic": True}
    assert v3_events["m07-v2-002"]["migratedFrom"] == 2

    assert invalid_target.status_code == 422
    assert unknown_stored.status_code == 500
