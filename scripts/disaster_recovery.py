#!/usr/bin/env python
"""
disaster_recovery.py — Simulacion de desastre y recuperacion con fixture sintetico.

Uso:
    python scripts/disaster_recovery.py

Salida:
    Imprime un resumen JSON y retorna exit code 0 si la recuperacion fue exitosa.
    Escribe artifacts/m06-resultados.json con los metricas de la operacion.

El script:
1. Obtiene la tabla DynamoDB (DynamoDB Local via Docker o AWS).
2. Simula un "desastre" borrando todos los eventos de la tabla.
3. Lee el fixture de datos sinteticos desde tests/fixtures/recovery_fixture.json.
4. Restaura los datos y mide el tiempo y la cantidad de registros recuperados.
5. Verifica que la cantidad de registros restaurados coincida con el fixture.
"""
import json
import sys
import time
from pathlib import Path

# Agrega el directorio raiz al path para importar src.*
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.nosql import dynamodb_resource, TABLE_NAME


def simulate_disaster(table) -> int:
    """Elimina todos los items de la tabla. Retorna la cantidad eliminada."""
    deleted = 0
    scan_kwargs = {"ProjectionExpression": "game_id, event_key"}
    while True:
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={
                    "game_id": item["game_id"],
                    "event_key": item["event_key"],
                })
                deleted += 1
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    return deleted


def restore_from_fixture(table, fixture_path: Path) -> int:
    """Carga los items del fixture y los inserta en DynamoDB. Retorna la cantidad restaurada."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    items = fixture["items"]
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    return len(items)


def verify_restore(table, expected_count: int) -> bool:
    """Verifica que la tabla tenga al menos expected_count items."""
    response = table.scan(Select="COUNT")
    actual = response.get("Count", 0)
    return actual >= expected_count


def main():
    fixture_path = Path(__file__).parent.parent / "tests" / "fixtures" / "recovery_fixture.json"
    if not fixture_path.is_file():
        print(f"ERROR: fixture no encontrado en {fixture_path}", file=sys.stderr)
        sys.exit(1)

    resource = dynamodb_resource()
    table = resource.Table(TABLE_NAME)

    print(f"[disaster_recovery] Iniciando simulacion de desastre en tabla '{TABLE_NAME}'...")

    # 1. Simular desastre (borrado de todos los eventos)
    t0 = time.perf_counter()
    deleted = simulate_disaster(table)
    t_disaster = time.perf_counter() - t0
    print(f"[disaster_recovery] Desastre simulado: {deleted} registros eliminados en {t_disaster:.2f}s")

    # 2. Restaurar desde fixture
    t1 = time.perf_counter()
    restored = restore_from_fixture(table, fixture_path)
    t_restore = time.perf_counter() - t1
    print(f"[disaster_recovery] Recuperacion completada: {restored} registros restaurados en {t_restore:.2f}s")

    # 3. Verificar restauracion
    verified = verify_restore(table, restored)
    status = "success" if verified else "failure"
    print(f"[disaster_recovery] Verificacion: {status}")

    # 4. Generar artifacts/m06-resultados.json
    results = {
        "assignmentId": "m06-recovery",
        "table": TABLE_NAME,
        "fixture": str(fixture_path.relative_to(fixture_path.parent.parent)),
        "disaster": {
            "records_deleted": deleted,
            "duration_seconds": round(t_disaster, 4),
        },
        "recovery": {
            "records_restored": restored,
            "duration_seconds": round(t_restore, 4),
        },
        "verification": {
            "status": status,
            "expected": restored,
            "verified": verified,
        },
    }

    artifacts_dir = Path(__file__).parent.parent / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "m06-resultados.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[disaster_recovery] Reporte escrito en artifacts/m06-resultados.json")

    if not verified:
        print("ERROR: La verificacion de recuperacion fallo.", file=sys.stderr)
        sys.exit(1)

    return results


if __name__ == "__main__":
    main()
