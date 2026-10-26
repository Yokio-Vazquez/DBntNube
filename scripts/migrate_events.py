#!/usr/bin/env python
"""Migracion repetible y rollback selectivo de documentos DynamoDB.

Detener todos los escritores y otros migradores antes de ejecutar el script.
Las condiciones comprueban existencia y version, pero no detectan cambios
concurrentes en otros atributos.
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.event_schemas import (  # noqa: E402
    detect_version,
    downcast_from_v3,
    normalize_event,
    upcast_to_v3,
)
from src.nosql import dynamodb_resource  # noqa: E402

FIXTURE_PATH = "tests/fixtures/m07_mixed_versions.json"
DEFAULT_REPORT = "artifacts/m07-migration-results.json"


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == 0:
            return {"$decimal": "0"}
        number = format(value, "f")
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        return {"$decimal": number or "0"}
    if isinstance(value, bytes):
        return {"$binary": base64.b64encode(value).decode("ascii")}
    if isinstance(value, set):
        return sorted(value, key=lambda item: json.dumps(item, default=_json_default))
    raise TypeError(f"Tipo no serializable en JSON: {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=_json_default
    )


def _scan_items(table: Any):
    scan_kwargs: dict[str, Any] = {}
    while True:
        response = table.scan(**scan_kwargs)
        yield from response.get("Items", [])
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key


def _snapshot(table: Any) -> str:
    items = sorted(_canonical_json(item) for item in _scan_items(table))
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()


def _failed_item(item: dict, error: Exception) -> dict:
    return {
        "game_id": item.get("game_id"),
        "event_key": item.get("event_key"),
        "reason": str(error),
    }


def _put_item(table: Any, item: dict, condition: Any) -> bool:
    try:
        table.put_item(Item=item, ConditionExpression=condition)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


def migrate_table(table: Any, dry_run: bool = False) -> dict:
    started = time.perf_counter()
    result = {
        "operation": "migrate",
        "scanned": 0,
        "migrated": 0,
        "skipped": 0,
        "failed": [],
    }

    for item in _scan_items(table):
        result["scanned"] += 1
        try:
            version = detect_version(item)
            if version == 3:
                normalize_event(item)
                result["skipped"] += 1
                continue
            migrated = upcast_to_v3(item)
        except (TypeError, ValueError, KeyError) as error:
            result["failed"].append(_failed_item(item, error))
            continue

        if dry_run:
            result["migrated"] += 1
            continue

        version_condition = (
            Attr("schemaVersion").eq(item["schemaVersion"])
            if "schemaVersion" in item
            else Attr("schemaVersion").not_exists()
        )
        if _put_item(
            table,
            migrated,
            Attr("game_id").exists()
            & Attr("event_key").exists()
            & version_condition,
        ):
            result["migrated"] += 1
        else:
            result["skipped"] += 1

    result["durationSeconds"] = round(time.perf_counter() - started, 4)
    return result


def rollback_table(table: Any, dry_run: bool = False) -> dict:
    started = time.perf_counter()
    result = {
        "operation": "rollback",
        "scanned": 0,
        "rolledBack": 0,
        "skipped": 0,
        "failed": [],
    }

    for item in _scan_items(table):
        result["scanned"] += 1
        try:
            version = detect_version(item)
            if version != 3 or "migratedFrom" not in item:
                normalize_event(item)
                result["skipped"] += 1
                continue
            restored = downcast_from_v3(item)
        except (TypeError, ValueError, KeyError) as error:
            result["failed"].append(_failed_item(item, error))
            continue

        if dry_run:
            result["rolledBack"] += 1
            continue

        if _put_item(
            table,
            restored,
            Attr("game_id").exists()
            & Attr("event_key").exists()
            & Attr("schemaVersion").eq(3)
            & Attr("migratedFrom").eq(item["migratedFrom"]),
        ):
            result["rolledBack"] += 1
        else:
            result["skipped"] += 1

    result["durationSeconds"] = round(time.perf_counter() - started, 4)
    return result


def _read_report(path: Path, table_name: str) -> dict:
    if not path.exists():
        return {
            "assignmentId": "m07-document-evolution",
            "table": table_name,
            "fixture": FIXTURE_PATH,
            "runs": [],
            "initialSnapshot": None,
        }

    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(report.get("runs"), list):
        raise ValueError(f"El reporte existente no tiene el formato esperado: {path}")
    if report.get("assignmentId") != "m07-document-evolution":
        raise ValueError(f"El reporte existente tiene un assignmentId inválido: {path}")
    if report.get("table") != table_name:
        raise ValueError(
            f"El reporte pertenece a la tabla '{report.get('table')}', "
            f"no a '{table_name}'. Usa otra ruta con --report."
        )
    for run in report["runs"]:
        counters = (
            ("scanned", "migrated", "skipped")
            if isinstance(run, dict) and run.get("operation") == "migrate"
            else ("scanned", "rolledBack", "skipped")
        )
        if (
            not isinstance(run, dict)
            or run.get("operation") not in {"migrate", "rollback"}
            or not isinstance(run.get("dryRun"), bool)
            or not isinstance(run.get("failed"), int)
            or not isinstance(run.get("failureDetails"), list)
            or len(run["failureDetails"]) != run["failed"]
            or any(
                not isinstance(run.get(counter), int) or run[counter] < 0
                for counter in (*counters, "failed")
            )
            or any(
                not isinstance(run.get(field), str)
                or len(run[field]) != 64
                for field in ("snapshotBefore", "snapshotAfter")
            )
        ):
            raise ValueError(f"El reporte existente contiene una corrida inválida: {path}")
    initial_snapshot = report.get("initialSnapshot")
    if initial_snapshot is not None and (
        not isinstance(initial_snapshot, str)
        or len(initial_snapshot) != 64
        or any(char not in "0123456789abcdef" for char in initial_snapshot)
    ):
        raise ValueError(f"El reporte existente tiene un snapshot inválido: {path}")
    report.setdefault("fixture", FIXTURE_PATH)
    report.setdefault("initialSnapshot", None)
    return report


def _update_verification_flags(report: dict) -> None:
    runs = [run for run in report["runs"] if not run["dryRun"]]
    report["idempotent"] = any(
        left["operation"] == right["operation"] == "migrate"
        and left["snapshotAfter"] == right["snapshotBefore"]
        and right["snapshotBefore"] == right["snapshotAfter"]
        and right["migrated"] == 0
        for left, right in zip(runs, runs[1:])
    )

    rollback_run = runs[-1] if runs else {}
    report["rollbackVerified"] = (
        rollback_run.get("operation") == "rollback"
        and report.get("initialSnapshot") is not None
        and rollback_run["snapshotAfter"] == report["initialSnapshot"]
    )


def _record_run(
    report_path: Path,
    report: dict,
    result: dict,
    dry_run: bool,
    snapshot_before: str,
    snapshot_after: str,
) -> dict:
    if result["operation"] == "migrate" and not dry_run:
        report["initialSnapshot"] = report.get("initialSnapshot") or snapshot_before
    report_run = {key: value for key, value in result.items() if key != "failed"}
    report_run["failed"] = len(result["failed"])
    report_run["failureDetails"] = result["failed"]
    report_run["dryRun"] = dry_run
    report_run["snapshotBefore"] = snapshot_before
    report_run["snapshotAfter"] = snapshot_after
    report["runs"].append(report_run)
    _update_verification_flags(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            report, indent=2, ensure_ascii=False, default=_json_default
        ) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="La operación requiere escritores y otros migradores detenidos.",
    )
    parser.add_argument(
        "--rollback", action="store_true", help="Revertir documentos migrados"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Contar sin escribir cambios"
    )
    parser.add_argument(
        "--table",
        default=os.getenv("DYNAMODB_TABLE", "cdrl_events"),
        help="Tabla DynamoDB (por defecto: DYNAMODB_TABLE)",
    )
    parser.add_argument(
        "--report",
        default=DEFAULT_REPORT,
        help=f"Ruta del reporte acumulativo (por defecto: {DEFAULT_REPORT})",
    )
    args = parser.parse_args(argv)
    report_path = Path(args.report)

    try:
        report = _read_report(report_path, args.table)
        table = dynamodb_resource().Table(args.table)
        snapshot_before = _snapshot(table)
        operation = rollback_table if args.rollback else migrate_table
        result = operation(table, dry_run=args.dry_run)
        snapshot_after = _snapshot(table)
        report = _record_run(
            report_path,
            report,
            result,
            args.dry_run,
            snapshot_before,
            snapshot_after,
        )
    except (ClientError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    output = dict(result)
    output["failed"] = len(result["failed"])
    output["failureDetails"] = result["failed"]
    output["report"] = str(args.report)
    output["idempotent"] = report["idempotent"]
    output["rollbackVerified"] = report["rollbackVerified"]
    print(json.dumps(output, indent=2, ensure_ascii=False, default=_json_default))
    if result["failed"]:
        for failure in result["failed"]:
            print(
                json.dumps(failure, ensure_ascii=False, default=_json_default),
                file=sys.stderr,
            )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
