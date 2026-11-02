from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

import scripts.m08_benchmark as benchmark
from src.event_schemas import normalize_event


@pytest.mark.parametrize(
    ("p", "expected"),
    [(50, 50.0), (95, 95.0), (0, 1.0), (100, 100.0)],
)
def test_percentile_uses_nearest_rank(p, expected):
    assert benchmark.percentile(list(range(1, 101)), p) == expected


def test_percentile_accepts_one_sample_and_rejects_empty_or_invalid_probability():
    assert benchmark.percentile([2.5], 95) == 2.5
    with pytest.raises(ValueError):
        benchmark.percentile([], 50)
    with pytest.raises(ValueError):
        benchmark.percentile([1], 101)


def test_generate_events_is_seeded_and_has_hot_game_and_timestamp_ties():
    events = benchmark.generate_events(seed=41, events=100, games=5, hot_share=0.6)

    assert events == benchmark.generate_events(
        seed=41, events=100, games=5, hot_share=0.6
    )
    assert events != benchmark.generate_events(
        seed=42, events=100, games=5, hot_share=0.6
    )
    assert sum(item["game_id"] == 1 for item in events) == 60
    assert sum(
        item["occurred_at"] == "2025-01-01T00:00:00Z" for item in events
    ) == 5
    for item in events:
        assert item["source"] == "synthetic-load"
        assert normalize_event(item).schema_version == 2


@pytest.mark.parametrize(
    ("events", "games", "hot_share"),
    [(0, 2, 0.6), (1, 1, 0.6), (1, 2, 0), (1, 2, 1.1)],
)
def test_generate_events_rejects_invalid_arguments(events, games, hot_share):
    with pytest.raises(ValueError):
        benchmark.generate_events(1, events, games, hot_share)


def test_full_mode_multiplies_event_count_and_iterations_by_five(monkeypatch):
    for name, value in {
        "M08_BENCH_EVENTS": "100",
        "M08_BENCH_GAMES": "5",
        "M08_BENCH_HOT_GAME_SHARE": "0.6",
        "M08_BENCH_ITERATIONS": "10",
        "M08_BENCH_WARMUP": "2",
        "M08_BENCH_PAGE_SIZE": "5",
        "M08_BENCH_DEEP_PAGE": "2",
        "M08_BENCH_SEED": "42",
    }.items():
        monkeypatch.setenv(name, value)

    quick = benchmark._settings("quick")
    full = benchmark._settings("full")

    assert full["events"] == quick["events"] * 5
    assert full["iterations"] == quick["iterations"] * 5
    assert full["warmup"] == quick["warmup"]


def test_bench_table_name_adds_suffix_and_rejects_production(monkeypatch):
    monkeypatch.setenv("DYNAMODB_TABLE_M08_TEST", "cdrl_events_m08_test")
    monkeypatch.setenv("DYNAMODB_TABLE", "cdrl_events")
    assert benchmark.bench_table_name("unit") == "cdrl_events_m08_test_unit"

    monkeypatch.setenv("DYNAMODB_TABLE_M08_TEST", "cdrl_events")
    with pytest.raises(ValueError, match="aislada"):
        benchmark.bench_table_name("unit")

    monkeypatch.setenv("DYNAMODB_TABLE", "team-events")
    monkeypatch.setenv("DYNAMODB_TABLE_M08_TEST", "team-events")
    with pytest.raises(ValueError, match="aislada"):
        benchmark.bench_table_name("unit")


@pytest.mark.parametrize(
    ("with_index", "expected_indexes"),
    [(False, 1), (True, 2)],
)
def test_create_bench_table_uses_expected_gsis(
    monkeypatch, with_index, expected_indexes
):
    resource = MagicMock()
    client = resource.meta.client
    client.describe_table.return_value = {
        "Table": {
            "GlobalSecondaryIndexes": [
                {"IndexName": definition["IndexName"], "IndexStatus": "ACTIVE"}
                for definition in (
                    benchmark.GLOBAL_SECONDARY_INDEXES
                    if with_index
                    else [benchmark.EVENT_TYPE_INDEX_DEFINITION]
                )
            ]
        }
    }
    monkeypatch.setattr(benchmark, "dynamodb_resource", lambda: resource)

    assert benchmark.create_bench_table("unit-table", with_index) is resource.Table.return_value
    request = client.create_table.call_args.kwargs
    assert request["BillingMode"] == "PAY_PER_REQUEST"
    assert len(request["GlobalSecondaryIndexes"]) == expected_indexes
    has_game_time_key = "game_time_key" in {
        attribute["AttributeName"]
        for attribute in request["AttributeDefinitions"]
    }
    assert has_game_time_key is with_index


def test_baseline_offset_queries_all_pages_then_sorts_and_slices():
    table = MagicMock()
    table.query.side_effect = [
        {
            "Items": [
                {
                    "event_key": "tie-a",
                    "occurred_at": "2026-01-01T00:00:00Z",
                },
                {
                    "event_key": "older",
                    "occurred_at": "2025-01-01T00:00:00Z",
                },
            ],
            "ScannedCount": 2,
            "LastEvaluatedKey": {"game_id": 1, "event_key": "older"},
        },
        {
            "Items": [
                {
                    "event_key": "tie-b",
                    "occurred_at": "2026-01-01T00:00:00Z",
                }
            ],
            "ScannedCount": 1,
        },
    ]

    result = benchmark.baseline_offset_page(table, 1, 1, 1)

    assert [item["event_key"] for item in result["items"]] == ["tie-a"]
    assert result["scannedCount"] == 3
    assert table.query.call_args_list[1].kwargs["ExclusiveStartKey"] == {
        "game_id": 1,
        "event_key": "older",
    }


def test_comparison_ratios_and_verdict_are_calculated():
    def result(p95, items_read):
        return {
            "latencyMs": {"p50": p95 / 2, "p95": p95},
            "itemsRead": items_read,
        }

    comparison = benchmark._compare_scenarios(
        {
            "baseline_page1": result(10, 100),
            "indexed_page1": result(5, 50),
            "baseline_deep": result(20, 200),
            "indexed_deep": result(10, 25),
            "baseline_walk": result(30, 600),
            "indexed_walk": result(35, 250),
        }
    )

    assert comparison["page1"]["p95Ratio"] == 2
    assert comparison["page1"]["itemsReadRatio"] == 2
    assert comparison["page1"]["verdict"] == "mejora observada"
    assert comparison["walk"]["verdict"] == "sin diferencia concluyente"


def test_scenario_samples_interleave_baseline_and_indexed_pairs():
    calls = []

    def scenario(name):
        def run():
            calls.append(name)
            return {"scannedCount": 1, "itemsReturned": 1}

        return run

    scenarios = {
        name: scenario(name)
        for name in (
            "baseline_page1",
            "indexed_page1",
            "baseline_deep",
            "indexed_deep",
            "baseline_walk",
            "indexed_walk",
        )
    }

    results = benchmark._measure_scenarios(scenarios, 2, 1, 20261031)

    assert len(calls) == 18
    for batch_start in (0, 6, 12):
        batch = calls[batch_start : batch_start + 6]
        for baseline, indexed in (
            ("baseline_page1", "indexed_page1"),
            ("baseline_deep", "indexed_deep"),
            ("baseline_walk", "indexed_walk"),
        ):
            assert abs(batch.index(baseline) - batch.index(indexed)) == 1
    assert all(result["samples"] == 2 for result in results.values())


class FakeDynamoTable:
    def __init__(self):
        self.items = {}

    @contextmanager
    def batch_writer(self):
        class Writer:
            def __init__(self, table):
                self.table = table

            def put_item(self, Item):
                self.table.put_item(Item=Item)

        yield Writer(self)

    def put_item(self, Item):
        self.items[(Item["game_id"], Item["event_key"])] = dict(Item)

    def query(self, **kwargs):
        index_query = "IndexName" in kwargs
        game_id = kwargs["KeyConditionExpression"].get_expression()["values"][1]
        items = [item for item in self.items.values() if item["game_id"] == game_id]
        if index_query:
            items.sort(key=lambda item: item["game_time_key"], reverse=True)
            start_key = kwargs.get("ExclusiveStartKey")
            if start_key:
                items = [
                    item
                    for item in items
                    if item["game_time_key"] < start_key["game_time_key"]
                ]
        else:
            items.sort(key=lambda item: item["event_key"])
            start_key = kwargs.get("ExclusiveStartKey")
            if start_key:
                start = next(
                    index
                    for index, item in enumerate(items)
                    if item["event_key"] == start_key["event_key"]
                ) + 1
                items = items[start:]

        limit = kwargs.get("Limit", 13)
        page = items[:limit]
        response = {"Items": page, "ScannedCount": len(page)}
        if len(items) > len(page):
            last_item = page[-1]
            response["LastEvaluatedKey"] = {
                "game_id": last_item["game_id"],
                "event_key": last_item["event_key"],
                **(
                    {"game_time_key": last_item["game_time_key"]}
                    if index_query
                    else {}
                ),
            }
        return response


class FakeDynamoClient:
    def __init__(self):
        self.tables = {}

    def create_table(self, **kwargs):
        self.tables[kwargs["TableName"]] = (
            FakeDynamoTable(),
            kwargs["GlobalSecondaryIndexes"],
        )

    def get_waiter(self, name):
        return MagicMock()

    def describe_table(self, TableName):
        table, indexes = self.tables[TableName]
        return {
            "Table": {
                "GlobalSecondaryIndexes": [
                    {"IndexName": index["IndexName"], "IndexStatus": "ACTIVE"}
                    for index in indexes
                ]
            }
        }

    def delete_table(self, TableName):
        self.tables.pop(TableName, None)


class FakeDynamoResource:
    def __init__(self):
        self.meta = MagicMock()
        self.meta.client = FakeDynamoClient()

    def Table(self, name):
        return self.meta.client.tables[name][0]


def test_quick_benchmark_runs_and_deletes_its_isolated_tables(monkeypatch):
    resource = FakeDynamoResource()
    monkeypatch.setattr(benchmark, "dynamodb_resource", lambda: resource)
    monkeypatch.setenv("DYNAMODB_TABLE_M08_TEST", "cdrl_events_m08_test")
    monkeypatch.setenv("DYNAMODB_TABLE", "cdrl_events")
    monkeypatch.setenv("DYNAMODB_ENDPOINT_URL", "http://127.0.0.1:8000")
    for name, value in {
        "M08_BENCH_EVENTS": "30",
        "M08_BENCH_GAMES": "3",
        "M08_BENCH_HOT_GAME_SHARE": "0.6",
        "M08_BENCH_ITERATIONS": "2",
        "M08_BENCH_WARMUP": "1",
        "M08_BENCH_PAGE_SIZE": "3",
        "M08_BENCH_DEEP_PAGE": "2",
        "M08_BENCH_SEED": "101",
    }.items():
        monkeypatch.setenv(name, value)

    original_baseline = benchmark.baseline_offset_page
    original_write_cost = benchmark._measure_write_cost
    read_calls = []
    write_calls = []

    def checked_baseline(table, *args):
        # All baseline reads (visibility, correctness, page/deep/walk) must
        # use the table with both GSIs, just like the indexed strategy.
        indexed = [t for t, indexes in resource.meta.client.tables.values()
                   if len(indexes) == 2]
        assert indexed == [table]
        read_calls.append(table)
        return original_baseline(table, *args)

    def checked_write_cost(baseline, indexed, *args):
        assert baseline is not indexed
        schemas = {id(t): indexes for t, indexes in resource.meta.client.tables.values()}
        assert len(schemas[id(baseline)]) == 1
        assert len(schemas[id(indexed)]) == 2
        write_calls.append((baseline, indexed))
        return original_write_cost(baseline, indexed, *args)

    monkeypatch.setattr(benchmark, "baseline_offset_page", checked_baseline)
    monkeypatch.setattr(benchmark, "_measure_write_cost", checked_write_cost)
    artifact = benchmark.run_benchmark("quick")
    repeated = benchmark.run_benchmark("quick")
    assert read_calls and len(write_calls) == 2
    assert artifact["readComparison"]["baselineTable"] == artifact["readComparison"]["indexedTable"]
    assert artifact["writeComparison"]["baselineTable"] != artifact["writeComparison"]["indexedTable"]

    assert artifact["correctness"]["sameResultSet"] is True
    assert artifact["gate"]["passed"] is True
    assert artifact["environment"]["target"] == "dynamodb-local"
    assert artifact["dataset"]["source"] == "synthetic-load"
    assert artifact["writeCost"]["billingCostObserved"] is False
    assert all(
        scenario["samples"] == 2 and scenario["errors"] == 0
        for scenario in artifact["scenarios"].values()
    )
    assert artifact["dataset"] == repeated["dataset"]
    assert {
        name: scenario["itemsRead"]
        for name, scenario in artifact["scenarios"].items()
    } == {
        name: scenario["itemsRead"]
        for name, scenario in repeated["scenarios"].items()
    }
    assert resource.meta.client.tables == {}


def test_cli_returns_two_when_deterministic_gate_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        benchmark,
        "run_benchmark",
        lambda mode: {
            "correctness": {"sameResultSet": True},
            "gate": {"passed": False},
        },
    )

    exit_code = benchmark.main(
        ["--quick", "--output", str(tmp_path / "benchmark.json")]
    )

    assert exit_code == 2


@pytest.mark.parametrize("transient", ["missing_page", "wrong_items", "final_check"])
def test_index_visibility_retries_until_pages_match(monkeypatch, transient):
    table = FakeDynamoTable()
    events = benchmark.generate_events(42, 30, 3, 0.6)
    benchmark.load_events(table, [benchmark.with_time_key(item) for item in events])
    original_page = benchmark._indexed_page
    original_check = benchmark._check_correctness
    calls = []
    sleeps = []

    def delayed_page(*args):
        calls.append(args[-1])
        if len(calls) == 2:
            if transient == "missing_page":
                raise benchmark.BenchmarkCorrectnessError("deep page not visible yet")
            if transient == "wrong_items":
                return {"items": []}
        return original_page(*args)

    checks = []

    def delayed_check(*args):
        checks.append(True)
        if transient == "final_check" and len(checks) == 1:
            raise benchmark.BenchmarkCorrectnessError("visibility changed")
        return original_check(*args)

    monkeypatch.setattr(benchmark, "_indexed_page", delayed_page)
    monkeypatch.setattr(benchmark, "_check_correctness", delayed_check)
    monkeypatch.setattr(benchmark.time, "sleep", sleeps.append)
    assert benchmark._wait_for_index(table, table, 1, 3, 2, 18)["sameResultSet"]
    assert sleeps == [1]


def test_index_visibility_times_out_without_reporting_success(monkeypatch):
    table = FakeDynamoTable()
    events = benchmark.generate_events(42, 30, 3, 0.6)
    benchmark.load_events(table, [benchmark.with_time_key(item) for item in events])
    sleeps = []

    def missing_page(*args):
        raise benchmark.BenchmarkCorrectnessError("not visible")

    monkeypatch.setattr(benchmark, "_indexed_page", missing_page)
    monkeypatch.setattr(benchmark.time, "sleep", sleeps.append)
    with pytest.raises(benchmark.BenchmarkCorrectnessError, match="visibilidad"):
        benchmark._wait_for_index(table, table, 1, 3, 2, 18)
    assert len(sleeps) == 60


def test_index_visibility_does_not_hide_service_errors(monkeypatch):
    from botocore.exceptions import EndpointConnectionError
    table = FakeDynamoTable()
    benchmark.load_events(table, [benchmark.with_time_key(item) for item in
                                benchmark.generate_events(42, 30, 3, 0.6)])
    sleeps = []

    def unavailable(*args):
        raise EndpointConnectionError(endpoint_url="http://invalid")

    monkeypatch.setattr(benchmark, "_indexed_page", unavailable)
    monkeypatch.setattr(benchmark.time, "sleep", sleeps.append)
    with pytest.raises(EndpointConnectionError):
        benchmark._wait_for_index(table, table, 1, 3, 2, 18)
    assert sleeps == []
