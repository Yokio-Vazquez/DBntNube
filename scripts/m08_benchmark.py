#!/usr/bin/env python
"""Reproducible DynamoDB benchmark for M08 pagination and index trade-offs."""
import argparse
import copy
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.event_schemas import normalize_event
from src.nosql import (
    ATTRIBUTE_DEFINITIONS,
    EVENT_TYPE_INDEX_DEFINITION,
    GAME_TIME_INDEX_DEFINITION,
    GLOBAL_SECONDARY_INDEXES,
    TABLE_KEY_SCHEMA,
    dynamodb_resource,
    query_events_page,
    with_time_key,
)

ASSIGNMENT_ID = "m08-pagination-performance"
LOCAL_IMAGE = "amazon/dynamodb-local:2.5.2"
QUICK_OUTPUT = "artifacts/m08-benchmark-results.json"
FULL_OUTPUT = "artifacts/m08-benchmark-full.json"


class BenchmarkCorrectnessError(RuntimeError):
    pass


def bench_table_name(suffix: str | None = None) -> str:
    base = os.getenv("DYNAMODB_TABLE_M08_TEST", "cdrl_events_m08_test")
    production_table = os.getenv("DYNAMODB_TABLE", "cdrl_events")
    if not base or base in {"cdrl_events", production_table}:
        raise ValueError("DYNAMODB_TABLE_M08_TEST debe ser una tabla aislada.")
    suffix = suffix or uuid.uuid4().hex[:12]
    name = f"{base}_{suffix}"
    if len(name) > 255 or any(
        not (character.isalnum() or character in "_.-") for character in name
    ):
        raise ValueError("Nombre de tabla de benchmark inválido.")
    return name


def create_bench_table(name: str, with_game_time_index: bool = True):
    production_table = os.getenv("DYNAMODB_TABLE", "cdrl_events")
    if name in {"cdrl_events", production_table}:
        raise ValueError("El benchmark no puede crear ni modificar la tabla de producción.")

    indexes = (
        GLOBAL_SECONDARY_INDEXES
        if with_game_time_index
        else [EVENT_TYPE_INDEX_DEFINITION]
    )
    key_attributes = {
        key["AttributeName"]
        for key in TABLE_KEY_SCHEMA
    }
    for index in indexes:
        key_attributes.update(
            key["AttributeName"] for key in index["KeySchema"]
        )
    attributes = [
        attribute
        for attribute in ATTRIBUTE_DEFINITIONS
        if attribute["AttributeName"] in key_attributes
    ]

    resource = dynamodb_resource()
    client = resource.meta.client
    client.create_table(
        TableName=name,
        KeySchema=copy.deepcopy(TABLE_KEY_SCHEMA),
        AttributeDefinitions=copy.deepcopy(attributes),
        GlobalSecondaryIndexes=copy.deepcopy(indexes),
        BillingMode="PAY_PER_REQUEST",
    )
    try:
        client.get_waiter("table_exists").wait(TableName=name)
        expected_indexes = {index["IndexName"] for index in indexes}
        for _ in range(120):
            description = client.describe_table(TableName=name)["Table"]
            active_indexes = {
                index["IndexName"]
                for index in description.get("GlobalSecondaryIndexes", [])
                if index.get("IndexStatus") == "ACTIVE"
            }
            if expected_indexes <= active_indexes:
                return resource.Table(name)
            time.sleep(1)
        raise TimeoutError(f"Los índices no quedaron ACTIVE en la tabla {name}.")
    except (BotoCoreError, ClientError, TimeoutError):
        client.delete_table(TableName=name)
        raise


def generate_events(
    seed: int,
    events: int,
    games: int,
    hot_share: float,
) -> list[dict]:
    if events < 1 or games < 2 or not 0 < hot_share <= 1:
        raise ValueError("events >= 1, games >= 2 y 0 < hot_share <= 1 son requeridos.")

    rng = random.Random(seed)
    hot_events = round(events * hot_share)
    game_ids = [1] * hot_events + [
        rng.randint(2, games) for _ in range(events - hot_events)
    ]
    rng.shuffle(game_ids)

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tied_timestamp = "2025-01-01T00:00:00Z"
    tied_events = max(1, events // 20)
    generated = []
    for index, game_id in enumerate(game_ids):
        occurred_at = (
            tied_timestamp
            if index < tied_events
            else (start + timedelta(seconds=rng.randrange(365 * 24 * 60 * 60)))
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        generated.append(
            {
                "game_id": game_id,
                "event_key": f"synthetic-{index:08d}-{rng.getrandbits(32):08x}",
                "event_type": rng.choice(
                    ("session_started", "session_ended", "achievement_unlocked")
                ),
                "occurred_at": occurred_at,
                "source": "synthetic-load",
                "schemaVersion": 2,
            }
        )
    return generated


def load_events(table: Any, items: list[dict]) -> None:
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)


def baseline_offset_page(
    table: Any, game_id: int, limit: int, offset: int
) -> dict:
    if game_id <= 0 or limit < 1 or offset < 0:
        raise ValueError("game_id, limit u offset fuera de rango.")

    items = []
    scanned_count = 0
    query_kwargs = {"KeyConditionExpression": Key("game_id").eq(game_id)}
    while True:
        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        scanned_count += response.get("ScannedCount", 0)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        query_kwargs["ExclusiveStartKey"] = last_key

    items.sort(
        key=lambda item: (item["occurred_at"], item["event_key"]),
        reverse=True,
    )
    return {
        "items": items[offset : offset + limit],
        "scannedCount": scanned_count,
    }


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        raise ValueError("No se puede calcular un percentil sin muestras.")
    if not 0 <= p <= 100:
        raise ValueError("p debe estar entre 0 y 100.")
    ordered = sorted(samples)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return float(ordered[rank - 1])


def _settings(mode: str) -> dict:
    if mode not in {"quick", "full"}:
        raise ValueError("mode debe ser 'quick' o 'full'.")

    settings = {
        "events": int(os.getenv("M08_BENCH_EVENTS", "3000")),
        "games": int(os.getenv("M08_BENCH_GAMES", "5")),
        "hotShare": float(os.getenv("M08_BENCH_HOT_GAME_SHARE", "0.6")),
        "iterations": int(os.getenv("M08_BENCH_ITERATIONS", "40")),
        "warmup": int(os.getenv("M08_BENCH_WARMUP", "5")),
        "pageSize": int(os.getenv("M08_BENCH_PAGE_SIZE", "25")),
        "deepPage": int(os.getenv("M08_BENCH_DEEP_PAGE", "10")),
        "seed": int(os.getenv("M08_BENCH_SEED", "20261031")),
    }
    if mode == "full":
        settings["events"] *= 5
        settings["iterations"] *= 5

    if (
        settings["events"] < 1
        or settings["games"] < 2
        or not 0 < settings["hotShare"] <= 1
        or settings["iterations"] < 1
        or settings["warmup"] < 0
        or settings["pageSize"] < 1
        or settings["pageSize"] > 1000
        or settings["deepPage"] < 1
    ):
        raise ValueError("Configuración M08_BENCH fuera de rango.")
    hot_count = round(settings["events"] * settings["hotShare"])
    if hot_count < settings["deepPage"] * settings["pageSize"]:
        raise ValueError(
            "El juego caliente debe contener al menos deepPage * pageSize eventos."
        )
    return settings


def _indexed_page(table: Any, game_id: int, limit: int, page_number: int) -> dict:
    cursor = None
    page = {"items": [], "nextCursor": None, "scannedCount": 0}
    for _ in range(page_number):
        page = query_events_page(game_id, limit, cursor, table=table)
        if page["nextCursor"] is None and _ + 1 < page_number:
            raise BenchmarkCorrectnessError(
                f"El índice no contiene la página solicitada: {page_number}."
            )
        cursor = page["nextCursor"]
    return page


def _page_keys(page: dict) -> list[str]:
    return [item["event_key"] for item in page["items"]]


def _check_correctness(
    baseline_table: Any,
    indexed_table: Any,
    game_id: int,
    limit: int,
    deep_page: int,
) -> dict:
    checks = {}
    for label, offset, page_number in (
        ("page1", 0, 1),
        ("deep", (deep_page - 1) * limit, deep_page),
    ):
        baseline = baseline_offset_page(baseline_table, game_id, limit, offset)
        indexed = _indexed_page(indexed_table, game_id, limit, page_number)
        checks[label] = _page_keys(baseline) == _page_keys(indexed)
        if not checks[label]:
            raise BenchmarkCorrectnessError(
                f"La página {label} difiere entre línea base e índice."
            )
    return {"sameResultSet": all(checks.values()), "pages": checks}


def _walk_baseline(table: Any, game_id: int, limit: int, pages: int) -> dict:
    scanned = returned = 0
    items = []
    for page_number in range(pages):
        page = baseline_offset_page(
            table, game_id, limit, page_number * limit
        )
        items.extend(page["items"])
        scanned += page["scannedCount"]
        returned += len(page["items"])
        if len(page["items"]) < limit:
            break
    return {"items": items, "scannedCount": scanned, "itemsReturned": returned}


def _walk_indexed(table: Any, game_id: int, limit: int, pages: int) -> dict:
    cursor = None
    scanned = returned = 0
    items = []
    for _ in range(pages):
        page = query_events_page(game_id, limit, cursor, table=table)
        items.extend(page["items"])
        scanned += page["scannedCount"]
        returned += len(page["items"])
        cursor = page["nextCursor"]
        if cursor is None:
            break
    return {"items": items, "scannedCount": scanned, "itemsReturned": returned}


def _wait_for_index(
    baseline_table: Any,
    indexed_table: Any,
    game_id: int,
    limit: int,
    deep_page: int,
    expected_count: int,
) -> dict:
    for _ in range(60):
        baseline_all = baseline_offset_page(
            baseline_table, game_id, expected_count, 0
        )
        if baseline_all["scannedCount"] != expected_count:
            time.sleep(1)
            continue
        expected_page1 = _page_keys(
            baseline_offset_page(baseline_table, game_id, limit, 0)
        )
        expected_deep = _page_keys(
            baseline_offset_page(
                baseline_table, game_id, limit, (deep_page - 1) * limit
            )
        )
        page1 = _page_keys(_indexed_page(indexed_table, game_id, limit, 1))
        deep = _page_keys(
            _indexed_page(indexed_table, game_id, limit, deep_page)
        )
        if page1 == expected_page1 and deep == expected_deep:
            return _check_correctness(
                baseline_table, indexed_table, game_id, limit, deep_page
            )
        time.sleep(1)
    raise BenchmarkCorrectnessError(
        "El índice no alcanzó visibilidad completa para las páginas comparadas."
    )


def _latency_summary(samples: list[float]) -> dict:
    return {
        "p50": percentile(samples, 50),
        "p95": percentile(samples, 95),
        "mean": mean(samples),
        "min": min(samples),
        "max": max(samples),
    }


def _measure_scenarios(
    scenarios: dict[str, Any],
    iterations: int,
    warmup: int,
    seed: int,
) -> dict:
    measurements = {
        name: {"latencies": [], "itemsRead": 0, "itemsReturned": 0, "errors": 0}
        for name in scenarios
    }
    order_rng = random.Random(seed ^ 0x4D3038)

    def interleaved_order() -> list[str]:
        pairs = [
            ("baseline_page1", "indexed_page1"),
            ("baseline_deep", "indexed_deep"),
            ("baseline_walk", "indexed_walk"),
        ]
        order_rng.shuffle(pairs)
        order = []
        for baseline, indexed in pairs:
            order.extend(
                (baseline, indexed)
                if order_rng.getrandbits(1)
                else (indexed, baseline)
            )
        return order

    for _ in range(warmup):
        for name in interleaved_order():
            scenarios[name]()

    for _ in range(iterations):
        for name in interleaved_order():
            started = time.perf_counter_ns()
            result = scenarios[name]()
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            measurements[name]["latencies"].append(elapsed_ms)
            measurements[name]["itemsRead"] += result["scannedCount"]
            measurements[name]["itemsReturned"] += result["itemsReturned"]

    return {
        name: {
            "samples": len(data["latencies"]),
            "errors": data["errors"],
            "latencyMs": _latency_summary(data["latencies"]),
            "itemsRead": data["itemsRead"],
            "itemsReturned": data["itemsReturned"],
        }
        for name, data in measurements.items()
    }


def _compare_scenarios(results: dict) -> dict:
    comparison = {}
    for label, baseline_name, indexed_name in (
        ("page1", "baseline_page1", "indexed_page1"),
        ("deep", "baseline_deep", "indexed_deep"),
        ("walk", "baseline_walk", "indexed_walk"),
    ):
        baseline = results[baseline_name]
        indexed = results[indexed_name]
        base_latency = baseline["latencyMs"]
        indexed_latency = indexed["latencyMs"]

        def ratio(base: float, candidate: float) -> float | None:
            return round(base / candidate, 4) if candidate else None

        if (
            indexed_latency["p95"] < base_latency["p95"]
            and indexed["itemsRead"] < baseline["itemsRead"]
        ):
            verdict = "mejora observada"
        elif (
            indexed_latency["p95"] >= base_latency["p95"]
            and indexed["itemsRead"] > baseline["itemsRead"]
        ):
            verdict = "regresion observada"
        else:
            verdict = "sin diferencia concluyente"
        comparison[label] = {
            "p50Ratio": ratio(
                base_latency["p50"], indexed_latency["p50"]
            ),
            "p95Ratio": ratio(
                base_latency["p95"], indexed_latency["p95"]
            ),
            "itemsReadRatio": ratio(
                baseline["itemsRead"], indexed["itemsRead"]
            ),
            "verdict": verdict,
        }
    return comparison


def _measure_write_cost(
    baseline_table: Any,
    indexed_table: Any,
    events: list[dict],
    seed: int,
) -> dict:
    samples = min(len(events), 100)
    baseline_latencies = []
    indexed_latencies = []
    rng = random.Random(seed ^ 0x57524954)
    for index in range(samples):
        item = dict(events[index])
        item["event_key"] = f"benchmark-write-{index:08d}"
        item["occurred_at"] = (
            datetime(2027, 1, 1, tzinfo=timezone.utc)
            + timedelta(seconds=index)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        item["game_id"] = 1 + index % 5
        write_order = ["baseline", "indexed"]
        rng.shuffle(write_order)
        for strategy in write_order:
            target = baseline_table if strategy == "baseline" else indexed_table
            prepared = item if strategy == "baseline" else with_time_key(item)
            started = time.perf_counter_ns()
            target.put_item(Item=prepared)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            destination = (
                baseline_latencies if strategy == "baseline" else indexed_latencies
            )
            destination.append(elapsed_ms)
    baseline_summary = _latency_summary(baseline_latencies)
    indexed_summary = _latency_summary(indexed_latencies)
    return {
        "samples": samples,
        "baseline": {
            "latencyMs": baseline_summary,
        },
        "indexed": {
            "latencyMs": indexed_summary,
        },
        "p50DeltaMs": indexed_summary["p50"] - baseline_summary["p50"],
        "p95DeltaMs": indexed_summary["p95"] - baseline_summary["p95"],
        "billingCostObserved": False,
        "interpretation": (
            "La latencia de escritura se midió; el costo facturado y las WCU "
            "no se observan en esta corrida. En AWS, cada GSI proyectado agrega "
            "almacenamiento e implica capacidad de escritura adicional."
        ),
    }


def _commit_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run_benchmark(mode: str = "quick") -> dict:
    settings = _settings(mode)
    run_suffix = uuid.uuid4().hex[:12]
    baseline_name = bench_table_name(f"{run_suffix}_baseline")
    indexed_name = bench_table_name(f"{run_suffix}_indexed")
    created_names = []
    try:
        baseline_table = create_bench_table(
            baseline_name, with_game_time_index=False
        )
        created_names.append(baseline_name)
        indexed_table = create_bench_table(
            indexed_name, with_game_time_index=True
        )
        created_names.append(indexed_name)

        events = generate_events(
            settings["seed"],
            settings["events"],
            settings["games"],
            settings["hotShare"],
        )
        load_events(baseline_table, events)
        load_events(indexed_table, [with_time_key(item) for item in events])

        hot_game_count = sum(item["game_id"] == 1 for item in events)
        if hot_game_count < settings["deepPage"] * settings["pageSize"]:
            raise ValueError("El juego caliente es menor que la página profunda.")
        correctness = _wait_for_index(
            baseline_table,
            indexed_table,
            1,
            settings["pageSize"],
            settings["deepPage"],
            hot_game_count,
        )

        indexed_deep_cursor = None
        if settings["deepPage"] > 1:
            indexed_deep_cursor = _indexed_page(
                indexed_table, 1, settings["pageSize"], settings["deepPage"] - 1
            )["nextCursor"]
        if settings["deepPage"] > 1 and indexed_deep_cursor is None:
            raise BenchmarkCorrectnessError(
                "No se pudo precalcular el cursor de la página profunda."
            )

        scenarios = {
            "baseline_page1": lambda: _scenario_result(
                baseline_offset_page(baseline_table, 1, settings["pageSize"], 0)
            ),
            "indexed_page1": lambda: _scenario_result(
                query_events_page(1, settings["pageSize"], table=indexed_table)
            ),
            "baseline_deep": lambda: _scenario_result(
                baseline_offset_page(
                    baseline_table,
                    1,
                    settings["pageSize"],
                    (settings["deepPage"] - 1) * settings["pageSize"],
                )
            ),
            "indexed_deep": lambda: _scenario_result(
                query_events_page(
                    1,
                    settings["pageSize"],
                    indexed_deep_cursor,
                    table=indexed_table,
                )
            ),
            "baseline_walk": lambda: _walk_baseline(
                baseline_table,
                1,
                settings["pageSize"],
                settings["deepPage"],
            ),
            "indexed_walk": lambda: _walk_indexed(
                indexed_table,
                1,
                settings["pageSize"],
                settings["deepPage"],
            ),
        }
        results = _measure_scenarios(
            scenarios,
            settings["iterations"],
            settings["warmup"],
            settings["seed"],
        )
        comparison = _compare_scenarios(results)
        write_cost = _measure_write_cost(
            baseline_table,
            indexed_table,
            events,
            settings["seed"],
        )
        commit_sha = _commit_sha()
        generated_at = datetime.now(timezone.utc).isoformat()
        target = (
            "dynamodb-local"
            if os.getenv("DYNAMODB_ENDPOINT_URL", "").strip()
            else "aws-dynamodb"
        )
        artifact = {
            "assignmentId": ASSIGNMENT_ID,
            "table": indexed_name,
            "tables": {"baseline": baseline_name, "indexed": indexed_name},
            "mode": mode,
            "generatedAt": generated_at,
            "commitSha": commit_sha,
            "dataset": {
                "seed": settings["seed"],
                "events": len(events),
                "games": settings["games"],
                "hotGameId": 1,
                "hotGameEvents": hot_game_count,
                "hotGameShare": settings["hotShare"],
                "actualHotGameShare": hot_game_count / len(events),
                "tiedTimestamp": "2025-01-01T00:00:00Z",
                "tiedTimestampEvents": sum(
                    item["occurred_at"] == "2025-01-01T00:00:00Z"
                    for item in events
                ),
                "source": "synthetic-load",
            },
            "config": {
                "iterations": settings["iterations"],
                "warmup": settings["warmup"],
                "pageSize": settings["pageSize"],
                "deepPage": settings["deepPage"],
                "percentileMethod": "nearest-rank",
                "scenarioOrder": "seeded random interleaving",
            },
            "environment": {
                "target": target,
                "dynamodbLocalImage": LOCAL_IMAGE if target == "dynamodb-local" else None,
                "platform": platform.platform(),
                "pythonVersion": platform.python_version(),
                "cpuCount": os.cpu_count(),
                "ci": os.getenv("CI"),
                "commitSha": commit_sha,
                "generatedAt": generated_at,
            },
            "correctness": correctness,
            "scenarios": results,
            "comparison": comparison,
            "comparisonRatioDefinition": "baseline / indexed; > 1 favors indexed",
            "writeCost": write_cost,
            "gate": {
                "name": "indexed_deep.itemsRead < baseline_deep.itemsRead",
                "passed": results["indexed_deep"]["itemsRead"]
                < results["baseline_deep"]["itemsRead"],
            },
        }
        return artifact
    finally:
        cleanup_error = None
        for name in reversed(created_names):
            try:
                _delete_bench_table(name)
            except (BotoCoreError, ClientError) as error:
                cleanup_error = error
        if cleanup_error:
            raise cleanup_error


def _scenario_result(page: dict) -> dict:
    return {
        "items": page["items"],
        "scannedCount": page["scannedCount"],
        "itemsReturned": len(page["items"]),
    }


def _delete_bench_table(name: str) -> None:
    if name in {"cdrl_events", os.getenv("DYNAMODB_TABLE", "cdrl_events")}:
        raise ValueError("El benchmark no puede borrar la tabla de producción.")
    client = dynamodb_resource().meta.client
    try:
        client.delete_table(TableName=name)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return
        raise


def _write_artifact(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--quick", action="store_true", help="Corrida reproducible rápida (default)")
    mode_group.add_argument("--full", action="store_true", help="Multiplica eventos e muestras por cinco")
    parser.add_argument("--output", help="Ruta del artifact JSON")
    args = parser.parse_args(argv)
    mode = "full" if args.full else "quick"
    output = Path(args.output or (FULL_OUTPUT if mode == "full" else QUICK_OUTPUT))

    try:
        artifact = run_benchmark(mode)
        _write_artifact(output, artifact)
    except (
        BotoCoreError,
        ClientError,
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "artifact": str(output),
                "mode": mode,
                "correctness": artifact["correctness"],
                "gate": artifact["gate"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if artifact["gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
