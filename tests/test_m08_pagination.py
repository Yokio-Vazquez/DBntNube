"""
test_m08_pagination.py — Pruebas de integración M08 (Persona 3).

Se ejecutan contra DynamoDB Local REAL (sin tablas simuladas). Cada prueba usa
una tabla exclusiva derivada de DYNAMODB_TABLE_M08_TEST con sufijo único,
creada con la misma llave y los mismos GSIs que cdrl_events, y la elimina en
el teardown aunque la prueba falle. Nunca se usa cdrl_events.
Los documentos se preparan con ``with_time_key()`` y se espera a que sean
visibles en el GSI antes de paginar. Si DynamoDB no está disponible las
pruebas FALLAN (no se omiten).

| Tipo            | Prueba                                                         |
|-----------------|----------------------------------------------------------------|
| Normal          | test_normal_60_events_pages_25_25_10                           |
| Normal (API)    | test_normal_api_walk_hides_storage_key                         |
| Límite 1        | test_boundary_insertions_during_walk_are_stable_vs_offset      |
| Límite 2        | test_boundary_tied_timestamps_across_page_cut                  |
| Límite 2        | test_boundary_empty_game                                       |
| Límite 2        | test_boundary_exact_multiple_of_limit_has_no_empty_page        |
| Límite 2        | test_boundary_min_limit_one / test_boundary_max_limit_api      |
| Fallo declarado | test_failure_invalid_or_foreign_cursor_returns_400             |
| Fallo declarado | test_failure_invalid_parameters_return_422                     |
| Fallo declarado | test_failure_dynamodb_unreachable_returns_503                  |
| Compat          | test_compat_events_endpoint_unchanged                          |
| Compat          | test_compat_query_events_follows_1mb_continuation              |
| Benchmark       | test_benchmark_quick_artifact_structure_and_reproducibility    |
"""
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import scripts.m08_benchmark as bench
import src.main as api
import src.nosql as nosql
from src.pagination import encode_cursor

FORMAT = "%Y-%m-%dT%H:%M:%SZ"
BASE = datetime(2026, 10, 1, tzinfo=timezone.utc)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHARED_TABLES = {"cdrl_events"}


# ── Helpers ─────────────────────────────────────────────────────────────────
def at(**delta) -> str:
    return (BASE + timedelta(**delta)).strftime(FORMAT)


def make_event(game_id: int, index: int, *, occurred_at: str | None = None, prefix: str = "m08") -> dict:
    return {
        "game_id": game_id,
        "event_key": f"{prefix}-{index:04d}",
        "event_type": "session_started",
        "occurred_at": occurred_at or at(minutes=index),
        "source": "synthetic-fixture",
        "schemaVersion": 2,
    }


def expected_order(events: list[dict]) -> list[str]:
    ordered = sorted(events, key=lambda e: (e["occurred_at"], e["event_key"]), reverse=True)
    return [event["event_key"] for event in ordered]


def index_keys(table, game_id: int) -> set[str]:
    items = nosql._query_all(
        table.query,
        IndexName=nosql.GAME_TIME_INDEX,
        KeyConditionExpression=Key("game_id").eq(game_id),
        ProjectionExpression="event_key",
    )
    return {item["event_key"] for item in items}


def wait_visible(table, events: list[dict], timeout: float = 30.0) -> None:
    """Espera a que todos los documentos sean visibles en el GSI (consistencia eventual)."""
    expected: dict[int, set[str]] = {}
    for event in events:
        expected.setdefault(int(event["game_id"]), set()).add(event["event_key"])
    deadline = time.monotonic() + timeout
    while True:
        if all(keys <= index_keys(table, game_id) for game_id, keys in expected.items()):
            return
        if time.monotonic() > deadline:
            pytest.fail("Los documentos no fueron visibles en el GSI dentro del plazo.")
        time.sleep(0.2)


def seed(table, events: list[dict]) -> None:
    bench.load_events(table, [nosql.with_time_key(event) for event in events])
    wait_visible(table, events)


def walk(table, game_id: int, limit: int, cursor: str | None = None) -> list[dict]:
    pages = []
    while True:
        page = nosql.query_events_page(game_id, limit, cursor, table=table)
        pages.append(page)
        cursor = page["nextCursor"]
        if cursor is None:
            return pages
        assert len(pages) < 1000, "recorrido sin fin"


def keys_of(pages: list[dict]) -> list[str]:
    return [item["event_key"] for page in pages for item in page["items"]]


def drop_table(name: str) -> None:
    if name in SHARED_TABLES | {nosql.TABLE_NAME}:
        raise ValueError("Las pruebas M08 no pueden borrar la tabla compartida.")
    client = nosql.dynamodb_resource().meta.client
    try:
        client.delete_table(TableName=name)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        return
    client.get_waiter("table_not_exists").wait(TableName=name)


@pytest.fixture
def m08_table(monkeypatch):
    """Tabla exclusiva con ambos GSIs; se elimina al final aunque la prueba falle."""
    name = bench.bench_table_name(f"it_{uuid.uuid4().hex[:8]}")
    assert name not in SHARED_TABLES | {nosql.TABLE_NAME}
    table = bench.create_bench_table(name, with_game_time_index=True)
    try:
        monkeypatch.setattr(nosql, "TABLE_NAME", name)  # API y query_events usan la tabla aislada
        yield table
    finally:
        monkeypatch.undo()
        drop_table(name)


@pytest.fixture
def client():
    with TestClient(api.app) as test_client:
        yield test_client


# ── Normal ──────────────────────────────────────────────────────────────────
def test_normal_60_events_pages_25_25_10(m08_table):
    events = [make_event(1, i) for i in range(60)]
    noise = [make_event(2, i, prefix="other") for i in range(5)]
    seed(m08_table, events + noise)

    pages = walk(m08_table, 1, 25)

    assert [len(page["items"]) for page in pages] == [25, 25, 10]
    assert all(page["nextCursor"] for page in pages[:-1])
    assert pages[-1]["nextCursor"] is None
    keys = keys_of(pages)
    assert len(keys) == len(set(keys)) == 60
    assert keys == expected_order(events)  # orden desc por (occurred_at, event_key)
    assert all(int(item["game_id"]) == 1 for page in pages for item in page["items"])
    # Lookahead limit+1: cada página lee como mucho 26 elementos, no la partición completa.
    assert all(page["scannedCount"] <= 26 for page in pages)


def test_normal_api_walk_hides_storage_key(m08_table, client):
    events = [make_event(1, i) for i in range(60)]
    seed(m08_table, events)

    bodies, cursor = [], None
    while True:
        params = {"game_id": 1, "limit": 25, **({"cursor": cursor} if cursor else {})}
        response = client.get("/events/page", params=params)
        assert response.status_code == 200
        body = response.json()
        bodies.append(body)
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert [len(body["items"]) for body in bodies] == [25, 25, 10]
    assert all(set(body) == {"items", "nextCursor", "limit", "order"} for body in bodies)
    assert all(body["limit"] == 25 and body["order"] == "occurred_at_desc" for body in bodies)
    keys = [item["event_key"] for body in bodies for item in body["items"]]
    assert keys == expected_order(events)
    assert all("game_time_key" not in item for body in bodies for item in body["items"])


# ── Límite 1: inserciones durante el recorrido ──────────────────────────────
def test_boundary_insertions_during_walk_are_stable_vs_offset(m08_table):
    originals = [make_event(1, i) for i in range(60)]
    seed(m08_table, originals)
    original_keys = set(expected_order(originals))

    # Ambas estrategias leen la página 1 ANTES de las inserciones.
    first_cursor_page = nosql.query_events_page(1, 25, table=m08_table)
    first_offset_page = bench.baseline_offset_page(m08_table, 1, 25, 0)
    assert keys_of([first_cursor_page]) == keys_of([first_offset_page])

    newer = [make_event(1, i, occurred_at=at(days=30, minutes=i), prefix="newer") for i in range(10)]
    older = [make_event(1, i, occurred_at=at(days=-30, minutes=i), prefix="older") for i in range(5)]
    seed(m08_table, newer + older)

    # Cursor (keyset): continuar desde el nextCursor emitido antes de insertar.
    cursor_keys = keys_of([first_cursor_page]) + keys_of(
        walk(m08_table, 1, 25, first_cursor_page["nextCursor"])
    )
    counts = Counter(cursor_keys)
    assert all(counts[key] == 1 for key in original_keys)  # originales exactamente una vez
    assert not {event["event_key"] for event in newer} & set(counts)  # más nuevos: no aparecen
    assert all(counts[event["event_key"]] <= 1 for event in older)  # más antiguos: como mucho una vez
    assert len(cursor_keys) == len(set(cursor_keys))
    assert cursor_keys == expected_order(originals + older)

    # Contraste offset: el mismo escenario SÍ duplica documentos.
    offset_keys = keys_of([first_offset_page])
    offset = 25
    while True:
        page = bench.baseline_offset_page(m08_table, 1, 25, offset)
        offset_keys.extend(keys_of([page]))
        if len(page["items"]) < 25:
            break
        offset += 25
    duplicates = [key for key, count in Counter(offset_keys).items() if count > 1]
    assert duplicates, "offset debía duplicar documentos tras insertar al inicio"
    assert len(duplicates) == len(newer)  # el desplazamiento equivale a los insertados al inicio
    assert set(duplicates) <= original_keys


# ── Límite 2: empates y bordes ──────────────────────────────────────────────
@pytest.mark.parametrize("limit", [7, 25])
def test_boundary_tied_timestamps_across_page_cut(m08_table, limit):
    tied_at = at(days=1)
    tied = [make_event(1, i, occurred_at=tied_at, prefix="tied") for i in range(30)]
    newer = [make_event(1, i, occurred_at=at(days=2, minutes=i), prefix="newer") for i in range(5)]
    seed(m08_table, tied + newer)

    pages = walk(m08_table, 1, limit)
    keys = keys_of(pages)

    assert len(keys) == len(set(keys)) == 35  # sin duplicados ni pérdidas
    assert keys == expected_order(tied + newer)  # empate resuelto por event_key desc
    # El corte cae dentro del grupo empatado al menos una vez.
    cut_items = [page["items"][-1] for page in pages[:-1]]
    assert any(item["occurred_at"] == tied_at for item in cut_items)


def test_boundary_empty_game(m08_table, client):
    seed(m08_table, [make_event(2, i) for i in range(3)])

    page = nosql.query_events_page(1, 25, table=m08_table)
    response = client.get("/events/page", params={"game_id": 1})

    assert page["items"] == [] and page["nextCursor"] is None
    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["nextCursor"] is None


def test_boundary_exact_multiple_of_limit_has_no_empty_page(m08_table):
    events = [make_event(1, i) for i in range(50)]
    seed(m08_table, events)

    pages = walk(m08_table, 1, 25)

    assert [len(page["items"]) for page in pages] == [25, 25]
    assert pages[0]["nextCursor"] is not None
    assert pages[1]["nextCursor"] is None  # sin una tercera página vacía
    assert keys_of(pages) == expected_order(events)


def test_boundary_min_limit_one(m08_table):
    events = [make_event(1, i) for i in range(5)]
    seed(m08_table, events)

    pages = walk(m08_table, 1, 1)

    assert [len(page["items"]) for page in pages] == [1, 1, 1, 1, 1]
    assert keys_of(pages) == expected_order(events)
    assert pages[-1]["nextCursor"] is None


def test_boundary_max_limit_api(m08_table, client):
    maximum = api.EVENTS_PAGE_MAX_LIMIT
    events = [make_event(1, i) for i in range(maximum + 1)]
    seed(m08_table, events)

    first = client.get("/events/page", params={"game_id": 1, "limit": maximum})
    assert first.status_code == 200
    second = client.get(
        "/events/page", params={"game_id": 1, "limit": maximum, "cursor": first.json()["nextCursor"]}
    )

    assert second.status_code == 200
    assert len(first.json()["items"]) == maximum and first.json()["nextCursor"]
    assert len(second.json()["items"]) == 1 and second.json()["nextCursor"] is None
    keys = [item["event_key"] for item in first.json()["items"] + second.json()["items"]]
    assert keys == expected_order(events)


# ── Fallo declarado ─────────────────────────────────────────────────────────
def test_failure_invalid_or_foreign_cursor_returns_400(m08_table, client):
    seed(m08_table, [make_event(1, i) for i in range(5)] + [make_event(2, i, prefix="g2") for i in range(5)])
    real_cursor = client.get("/events/page", params={"game_id": 1, "limit": 2}).json()["nextCursor"]
    assert real_cursor

    manipulated = [
        "!!!no-es-base64!!!",
        real_cursor[:-5],  # truncado
        encode_cursor({"game_id": 1, "occurred_at": "no-es-fecha", "event_key": "x"}),
        "x" * 4097,
    ]
    for cursor in manipulated:
        response = client.get("/events/page", params={"game_id": 1, "cursor": cursor})
        assert response.status_code == 400, cursor

    foreign = client.get("/events/page", params={"game_id": 2, "cursor": real_cursor})
    assert foreign.status_code == 400


@pytest.mark.parametrize(
    "params",
    [
        {"game_id": 1, "limit": 0},
        {"game_id": 1, "limit": "MAX+1"},
        {"game_id": 0},
        {"game_id": 1, "version": 9},
        {"limit": 10},
    ],
)
def test_failure_invalid_parameters_return_422(m08_table, client, params):
    if params.get("limit") == "MAX+1":
        params = {**params, "limit": api.EVENTS_PAGE_MAX_LIMIT + 1}
    assert client.get("/events/page", params=params).status_code == 422


def test_failure_dynamodb_unreachable_returns_503(m08_table, client, monkeypatch):
    monkeypatch.setenv("DYNAMODB_ENDPOINT_URL", "http://127.0.0.1:9")  # puerto sin servicio

    page = client.get("/events/page", params={"game_id": 1})
    full = client.get("/events", params={"game_id": 1})

    assert page.status_code == 503
    assert full.status_code == 503


# ── Compatibilidad ──────────────────────────────────────────────────────────
def test_compat_events_endpoint_unchanged(m08_table, client):
    events = [make_event(1, i) for i in range(40)] + [dict(e) for e in nosql.FIXTURE_EVENTS]
    seed(m08_table, events)
    game1 = {event["event_key"] for event in events if event["game_id"] == 1}

    response = client.get("/events", params={"game_id": 1})
    projected = client.get("/events", params={"game_id": 1, "version": 1})

    assert response.status_code == 200 and isinstance(response.json(), list)
    assert {item["event_key"] for item in response.json()} == game1
    assert all("game_time_key" not in item for item in response.json())
    assert projected.status_code == 200
    assert all(item["schemaVersion"] == 1 for item in projected.json())
    # /events y /events/page exponen el mismo conjunto de documentos.
    assert set(keys_of(walk(m08_table, 1, 25))) == game1


def test_compat_query_events_follows_1mb_continuation(m08_table):
    padding = "x" * 1000
    events = [dict(make_event(1, i), padding=padding) for i in range(1200)]  # > 1 MB
    seed(m08_table, events)

    raw = m08_table.query(KeyConditionExpression=Key("game_id").eq(1))
    result = nosql.query_events(1)

    assert "LastEvaluatedKey" in raw  # DynamoDB cortó la primera respuesta
    assert len(result) == 1200
    assert {item["event_key"] for item in result} == {event["event_key"] for event in events}


# ── Benchmark ───────────────────────────────────────────────────────────────
def test_benchmark_quick_artifact_structure_and_reproducibility(monkeypatch):
    settings = {
        "M08_BENCH_EVENTS": "400",
        "M08_BENCH_GAMES": "3",
        "M08_BENCH_HOT_GAME_SHARE": "0.6",
        "M08_BENCH_ITERATIONS": "3",
        "M08_BENCH_WARMUP": "1",
        "M08_BENCH_PAGE_SIZE": "10",
        "M08_BENCH_DEEP_PAGE": "5",
        "M08_BENCH_SEED": "20261031",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)

    first = bench.run_benchmark("quick")
    second = bench.run_benchmark("quick")

    for artifact in (first, second):
        assert artifact["assignmentId"] == "m08-pagination-performance"
        assert artifact["mode"] == "quick"
        assert artifact["table"] not in SHARED_TABLES | {nosql.TABLE_NAME}
        read, write = artifact["readComparison"], artifact["writeComparison"]
        assert read["baselineTable"] == read["indexedTable"] and read["samePhysicalTable"] is True
        assert write["baselineTable"] != write["indexedTable"]
        environment = artifact["environment"]
        assert environment["target"] == "dynamodb-local"
        assert environment["dynamodbLocalImage"] == bench.LOCAL_IMAGE
        assert {"platform", "pythonVersion", "cpuCount", "generatedAt"} <= set(environment)
        assert SHA_RE.match(environment["commitSha"])
        assert artifact["dataset"]["seed"] == 20261031
        assert artifact["correctness"]["sameResultSet"] is True
        assert set(artifact["scenarios"]) == {
            f"{strategy}_{kind}" for strategy in ("baseline", "indexed") for kind in ("page1", "deep", "walk")
        }
        for scenario in artifact["scenarios"].values():
            latency = scenario["latencyMs"]
            assert scenario["samples"] == 3 and scenario["errors"] == 0
            assert latency["min"] <= latency["p50"] <= latency["p95"] <= latency["max"]
        assert set(artifact["comparison"]) == {"page1", "deep", "walk"}
        assert all(
            entry["verdict"] in {"mejora observada", "regresion observada", "sin diferencia concluyente"}
            for entry in artifact["comparison"].values()
        )
        scenarios = artifact["scenarios"]
        assert scenarios["indexed_deep"]["itemsRead"] < scenarios["baseline_deep"]["itemsRead"]
        assert artifact["gate"]["passed"] is True
        assert artifact["writeCost"]["samples"] == 100

    # Reproducible: misma semilla -> mismo dataset y mismos elementos leídos.
    assert first["dataset"] == second["dataset"]
    assert {name: s["itemsRead"] for name, s in first["scenarios"].items()} == {
        name: s["itemsRead"] for name, s in second["scenarios"].items()
    }
    # Las tablas del benchmark se eliminaron.
    remaining = set(nosql.dynamodb_resource().meta.client.list_tables()["TableNames"])
    created = {*first["tables"].values(), *second["tables"].values()}
    assert not created & remaining
