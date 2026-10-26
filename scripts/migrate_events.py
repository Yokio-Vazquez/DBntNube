#!/usr/bin/env python
"""Migracion repetible de documentos de eventos y rollback selectivo."""
import argparse
import json
import os
import sys
import time
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


def _scan_items(table: Any):
    scan_kwargs: dict[str, Any] = {}
    while True:
        response = table.scan(**scan_kwargs)
        yield from response.get("Items", [])
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key


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

        if _put_item(
            table,
            migrated,
            Attr("schemaVersion").not_exists() | Attr("schemaVersion").ne(3),
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
            Attr("schemaVersion").eq(3) & Attr("migratedFrom").exists(),
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
        }

    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(report.get("runs"), list):
        raise ValueError(f"El reporte existente no tiene el formato esperado: {path}")
    if report.get("table") != table_name:
        raise ValueError(
            f"El reporte pertenece a la tabla '{report.get('table')}', "
            f"no a '{table_name}'. Usa otra ruta con --report."
        )
    report.setdefault("assignmentId", "m07-document-evolution")
    report.setdefault("fixture", FIXTURE_PATH)
    return report


def _update_verification_flags(report: dict) -> None:
    runs = report["runs"]
    report["idempotent"] = any(
        left["operation"] == right["operation"] == "migrate"
        and not left.get("dryRun")
        and not right.get("dryRun")
        and right["migrated"] == 0
        for left, right in zip(runs, runs[1:])
    )

    completed_runs = [run for run in runs if not run.get("dryRun")]
    rollback_run = completed_runs[-1] if completed_runs else {}
    previous_rollback = max(
        (
            index
            for index, run in enumerate(completed_runs[:-1])
            if run["operation"] == "rollback"
        ),
        default=-1,
    )
    migrated = sum(
        run["migrated"]
        for run in completed_runs[previous_rollback + 1 : -1]
        if run["operation"] == "migrate"
    )
    rolled_back = rollback_run.get("rolledBack", 0)
    report["rollbackVerified"] = (
        rollback_run.get("operation") == "rollback"
        and rolled_back >= migrated
        and (migrated > 0 or rolled_back > 0)
    )


def _record_run(report_path: Path, table_name: str, result: dict, dry_run: bool) -> dict:
    report = _read_report(report_path, table_name)
    report_run = {key: value for key, value in result.items() if key != "failed"}
    report_run["failed"] = len(result["failed"])
    report_run["dryRun"] = dry_run
    report["runs"].append(report_run)
    _update_verification_flags(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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

    try:
        table = dynamodb_resource().Table(args.table)
        operation = rollback_table if args.rollback else migrate_table
        result = operation(table, dry_run=args.dry_run)
        report = _record_run(Path(args.report), args.table, result, args.dry_run)
    except (ClientError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    output = dict(result)
    output["failed"] = len(result["failed"])
    output["report"] = str(args.report)
    output["idempotent"] = report["idempotent"]
    output["rollbackVerified"] = report["rollbackVerified"]
    print(json.dumps(output, indent=2, ensure_ascii=False))
    if result["failed"]:
        for failure in result["failed"]:
            print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
