#!/usr/bin/env python
"""Demo reproducible M07 sobre DynamoDB Local (Persona 3).

Secuencia: tabla aislada -> fixture -> migrate x2 -> rollback -> limpieza.

- La tabla se toma de DYNAMODB_TABLE_M07_TEST y nunca puede ser la tabla
  compartida (DYNAMODB_TABLE / cdrl_events).
- Cada escenario usa un reporte nuevo en un directorio temporal; el artifact
  final solo se reemplaza si todas las expectativas se cumplen.
- La tabla se elimina en ``finally`` aunque algo falle.

Salida: artifacts/m07-migration-results.json. Exit code 0 si la demo cumple
todas las expectativas, 1 en caso contrario.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from botocore.exceptions import BotoCoreError, ClientError  # noqa: E402

import scripts.migrate_events as migration  # noqa: E402
from src.nosql import (  # noqa: E402
    ATTRIBUTE_DEFINITIONS,
    EVENT_TYPE_INDEX_DEFINITION,
    TABLE_KEY_SCHEMA,
    dynamodb_resource,
)

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "m07_mixed_versions.json"
ARTIFACT_PATH = ROOT / "artifacts" / "m07-migration-results.json"
DEFAULT_TEST_TABLE = "cdrl_events_m07_test"
SHARED_TABLES = {"cdrl_events"}


# ── Helpers reutilizados por tests/test_m07_document_evolution.py ──────────
def isolated_table_name(suffix: str | None = None) -> str:
    """Nombre de la tabla exclusiva M07; rechaza la tabla compartida."""
    base = os.getenv("DYNAMODB_TABLE_M07_TEST") or DEFAULT_TEST_TABLE
    name = f"{base}_{suffix}" if suffix else base
    shared = SHARED_TABLES | {os.getenv("DYNAMODB_TABLE", "cdrl_events")}
    if name in shared:
        raise ValueError(
            f"La tabla M07 '{name}' coincide con la tabla compartida; "
            "configura DYNAMODB_TABLE_M07_TEST con otro nombre."
        )
    return name


def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_isolated_table(name: str):
    """Crea la tabla con la misma llave e índice que cdrl_events."""
    resource = dynamodb_resource()
    client = resource.meta.client
    client.create_table(
        TableName=name,
        KeySchema=TABLE_KEY_SCHEMA,
        AttributeDefinitions=ATTRIBUTE_DEFINITIONS,
        GlobalSecondaryIndexes=[EVENT_TYPE_INDEX_DEFINITION],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=name)
    return resource.Table(name)


def drop_table(name: str) -> None:
    """Elimina la tabla si existe (idempotente)."""
    client = dynamodb_resource().meta.client
    try:
        client.delete_table(TableName=name)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        return
    client.get_waiter("table_not_exists").wait(TableName=name)


def fixture_items() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["items"]


def load_items(table, items) -> None:
    for item in items:
        table.put_item(Item=item)


def scan_all(table) -> list[dict]:
    """Snapshot paginado y ordenado por llave (independiente del orden del scan)."""
    items = list(migration._scan_items(table))
    return sorted(items, key=lambda item: (int(item["game_id"]), item["event_key"]))


def run_cli(args: list[str]) -> int:
    """Ejecuta el CLI real de migración sin ensuciar la salida de make verify."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return migration.main(args)


# ── Demo ────────────────────────────────────────────────────────────────────
def _expectations(report: dict, exit_codes: list[int], initial: str, final: str) -> dict:
    runs = report["runs"]
    first, second, rollback = (runs + [{}, {}, {}])[:3]
    failure_keys = [f.get("event_key") for f in first.get("failureDetails", [])]
    return {
        "threeRealRuns": len(runs) == 3 and not any(run["dryRun"] for run in runs),
        "exitCodesDeclareInvalidDocument": exit_codes == [2, 2, 2],
        "firstMigration": (first.get("migrated"), first.get("skipped"), first.get("failed")) == (4, 1, 1),
        "invalidDocumentReported": failure_keys == ["m07-invalid"],
        "secondMigrationMigratesNothing": second.get("migrated") == 0,
        "secondMigrationLeavesTableIdentical": second.get("snapshotBefore") == second.get("snapshotAfter")
        == first.get("snapshotAfter"),
        "rollbackRestoresFour": rollback.get("rolledBack") == 4,
        "rollbackMatchesInitialSnapshot": rollback.get("snapshotAfter") == report.get("initialSnapshot") == initial
        and final == initial,
        "idempotent": report.get("idempotent") is True,
        "rollbackVerified": report.get("rollbackVerified") is True,
    }


def run_demo(artifact_path: Path = ARTIFACT_PATH) -> int:
    table_name = isolated_table_name()
    print(f"[m07_demo] Tabla aislada: {table_name}")
    try:
        drop_table(table_name)  # restos de una ejecución interrumpida
        table = create_isolated_table(table_name)
        load_items(table, fixture_items())
        initial = migration._snapshot(table)

        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "m07-migration-results.json"  # reporte nuevo
            args = ["--table", table_name, "--report", str(report_path)]
            exit_codes = [run_cli(args), run_cli(args), run_cli(["--rollback", *args])]
            final = migration._snapshot(table)
            report = json.loads(report_path.read_text(encoding="utf-8"))
    except (BotoCoreError, ClientError, OSError, ValueError) as error:
        print(f"ERROR: demo M07 no pudo ejecutarse: {error}", file=sys.stderr)
        return 1
    finally:
        try:
            drop_table(table_name)
            print(f"[m07_demo] Tabla {table_name} eliminada")
        except (BotoCoreError, ClientError) as error:
            print(f"ERROR: no se pudo eliminar {table_name}: {error}", file=sys.stderr)

    checks = _expectations(report, exit_codes, initial, final)
    report["fixture"] = FIXTURE_PATH.relative_to(ROOT).as_posix()
    report["generatedBy"] = "scripts/m07_demo.py"
    report["generatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report["cliExitCodes"] = exit_codes
    report["finalSnapshot"] = final
    report["expectations"] = checks

    for run in report["runs"]:
        moved = run.get("migrated", run.get("rolledBack"))
        print(
            f"[m07_demo] {run['operation']:<8} scanned={run['scanned']} "
            f"changed={moved} skipped={run['skipped']} failed={run['failed']}"
        )
    failed_checks = [name for name, ok in checks.items() if not ok]
    if failed_checks:
        print(f"ERROR: expectativas M07 no cumplidas: {', '.join(failed_checks)}", file=sys.stderr)
        return 1

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"[m07_demo] idempotent={report['idempotent']} rollbackVerified={report['rollbackVerified']} "
        f"-> {artifact_path.relative_to(ROOT).as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_demo())
