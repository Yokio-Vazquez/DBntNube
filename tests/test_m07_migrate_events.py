import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

import scripts.migrate_events as migration
from src.event_schemas import downcast_from_v3, upcast_to_v3

FIXTURE_PATH = Path("tests/fixtures/m07_mixed_versions.json")


def event(key, **fields):
    return {
        "game_id": 1,
        "event_key": key,
        "event_type": "session_started",
        "occurred_at": "2026-10-25T10:00:00Z",
        "source": "synthetic-fixture",
        **fields,
    }


class MemoryTable:
    def __init__(self, items=(), page_size=2):
        self.items = {
            (item["game_id"], item["event_key"]): deepcopy(item)
            for item in items
        }
        self.page_size = page_size
        self.scans = 0
        self.writes = []

    def _ordered_items(self):
        return sorted(
            self.items.values(),
            key=lambda item: (item["game_id"], item["event_key"]),
        )

    def scan(self, **kwargs):
        self.scans += 1
        items = self._ordered_items()
        start_key = kwargs.get("ExclusiveStartKey")
        if start_key:
            start = next(
                index
                for index, item in enumerate(items)
                if (item["game_id"], item["event_key"])
                == (start_key["game_id"], start_key["event_key"])
            ) + 1
        else:
            start = 0
        page = items[start : start + self.page_size]
        response = {"Items": deepcopy(page)}
        if start + self.page_size < len(items):
            last_item = page[-1]
            response["LastEvaluatedKey"] = {
                "game_id": last_item["game_id"],
                "event_key": last_item["event_key"],
            }
        return response

    def put_item(self, Item, ConditionExpression):
        self.writes.append((deepcopy(Item), ConditionExpression))
        self.items[(Item["game_id"], Item["event_key"])] = deepcopy(Item)

    def snapshot(self):
        return deepcopy(self._ordered_items())


def fixture_items():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["items"]


def expression_parts(expression):
    parts = [expression.get_expression()]
    for value in expression.get_expression()["values"]:
        if hasattr(value, "get_expression"):
            parts.extend(expression_parts(value))
        else:
            parts.append(value)
    return parts


def test_fixture_migrates_idempotently_and_rolls_back_to_exact_snapshot(
    tmp_path, monkeypatch, capsys
):
    initial_items = fixture_items()
    assert len(initial_items) == 6
    initial_items[-1]["game_id"] = Decimal("3")
    initial_items[-1]["schemaVersion"] = Decimal("99")
    table = MemoryTable(initial_items)
    before = table.snapshot()
    resource = MagicMock()
    resource.Table.return_value = table
    monkeypatch.setattr(migration, "dynamodb_resource", lambda: resource)
    report_path = tmp_path / "migration.json"
    args = ["--table", "cdrl_events_m07_test", "--report", str(report_path)]

    assert migration.main(args) == 2
    capsys.readouterr()
    after_first_migration = table.snapshot()
    assert len(table.writes) == 4
    assert migration.main(args) == 2
    capsys.readouterr()
    assert table.snapshot() == after_first_migration
    assert migration.main(["--rollback", *args]) == 2
    capsys.readouterr()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert table.snapshot() == before
    assert report["idempotent"] is True
    assert report["rollbackVerified"] is True
    assert report["runs"][1]["migrated"] == 0
    assert report["runs"][2]["rolledBack"] == 4
    assert report["runs"][0]["failed"] == 1
    assert report["runs"][0]["failureDetails"][0]["game_id"] == {
        "$decimal": "3"
    }
    restored_by_key = {
        item["event_key"]: item for item in table.snapshot()
    }
    assert restored_by_key["m07-v3-native"] == before[4]
    assert restored_by_key["m07-invalid"] == before[5]


def test_migration_condition_requires_existing_keys_and_exact_source_version():
    table = MemoryTable([event("v1"), event("v2", schemaVersion=2)])

    result = migration.migrate_table(table)

    assert result["migrated"] == 2
    v1_condition, v2_condition = [write[1] for write in table.writes]
    v1_parts = expression_parts(v1_condition)
    v2_parts = expression_parts(v2_condition)
    v1_names = {part.name for part in v1_parts if isinstance(part, Attr)}
    v2_names = {part.name for part in v2_parts if isinstance(part, Attr)}
    assert {"game_id", "event_key", "schemaVersion"} <= v1_names
    assert {"game_id", "event_key", "schemaVersion"} <= v2_names
    assert any(part == 2 for part in v2_parts)
    assert any(
        isinstance(part, dict)
        and part.get("operator") == "attribute_not_exists"
        for part in v1_parts
    )


def test_rollback_condition_checks_the_original_migrated_from_value():
    v3_document = upcast_to_v3(event("rollback", schemaVersion=2))
    table = MemoryTable([v3_document])

    result = migration.rollback_table(table)

    assert result["rolledBack"] == 1
    condition = table.writes[0][1]
    parts = expression_parts(condition)
    names = {part.name for part in parts if isinstance(part, Attr)}
    assert {"game_id", "event_key", "schemaVersion", "migratedFrom"} <= names
    assert 2 in parts


def test_previously_migrated_v3_rolls_back_to_its_original_v2():
    original = event("previously-migrated", schemaVersion=2, custom={"keep": 1})
    stored_v3 = upcast_to_v3(original)
    table = MemoryTable([stored_v3])
    initial_snapshot = table.snapshot()

    result = migration.rollback_table(table)

    assert result["rolledBack"] == 1
    assert table.snapshot() == [original]
    assert initial_snapshot[0]["schemaVersion"] == 3
    assert downcast_from_v3(stored_v3) == original


def test_dry_run_for_migration_and_rollback_never_changes_snapshot():
    legacy = event("legacy", custom={"untouched": True})
    migrated = upcast_to_v3(event("migrated", schemaVersion=2))
    table = MemoryTable([legacy, migrated])
    before = table.snapshot()

    migration_result = migration.migrate_table(table, dry_run=True)
    rollback_result = migration.rollback_table(table, dry_run=True)

    assert migration_result["migrated"] == 1
    assert rollback_result["rolledBack"] == 1
    assert table.snapshot() == before
    assert table.writes == []


def test_dry_run_snapshots_do_not_verify_idempotence_or_rollback(tmp_path):
    report = {
        "assignmentId": "m07-document-evolution",
        "table": "cdrl_events_m07_test",
        "fixture": "tests/fixtures/m07_mixed_versions.json",
        "runs": [],
        "initialSnapshot": None,
    }
    snapshot = "a" * 64
    migration._record_run(
        tmp_path / "dry-run.json",
        report,
        {
            "operation": "migrate",
            "scanned": 1,
            "migrated": 1,
            "skipped": 0,
            "failed": [],
        },
        True,
        snapshot,
        snapshot,
    )
    migration._record_run(
        tmp_path / "dry-run.json",
        report,
        {
            "operation": "rollback",
            "scanned": 1,
            "rolledBack": 1,
            "skipped": 0,
            "failed": [],
        },
        True,
        snapshot,
        snapshot,
    )

    assert report["idempotent"] is False
    assert report["rollbackVerified"] is False


def test_report_does_not_claim_success_from_counters_when_snapshots_differ():
    report = {
        "initialSnapshot": "a" * 64,
        "runs": [
            {
                "operation": "migrate",
                "migrated": 4,
                "dryRun": False,
                "snapshotBefore": "a" * 64,
                "snapshotAfter": "b" * 64,
            },
            {
                "operation": "migrate",
                "migrated": 0,
                "dryRun": False,
                "snapshotBefore": "c" * 64,
                "snapshotAfter": "d" * 64,
            },
            {
                "operation": "rollback",
                "rolledBack": 4,
                "dryRun": False,
                "snapshotBefore": "d" * 64,
                "snapshotAfter": "e" * 64,
            },
        ],
    }

    migration._update_verification_flags(report)

    assert report["idempotent"] is False
    assert report["rollbackVerified"] is False


def test_empty_table_migration_and_rollback_are_noops():
    table = MemoryTable([])

    migrated = migration.migrate_table(table)
    rolled_back = migration.rollback_table(table)

    assert migrated["scanned"] == migrated["migrated"] == migrated["skipped"] == 0
    assert rolled_back["scanned"] == rolled_back["rolledBack"] == rolled_back["skipped"] == 0


def test_scanner_follows_all_pages():
    table = MemoryTable([event(f"e-{index}") for index in range(5)], page_size=2)

    result = migration.migrate_table(table, dry_run=True)

    assert result["scanned"] == 5
    assert table.scans == 3


def test_conditional_write_conflict_is_skipped_for_migration_and_rollback():
    for operation, item in [
        (migration.migrate_table, event("migrate")),
        (
            migration.rollback_table,
            upcast_to_v3(event("rollback", schemaVersion=2)),
        ),
    ]:
        table = MagicMock()
        table.scan.return_value = {"Items": [item]}
        table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "PutItem",
        )

        result = operation(table)

        assert result["skipped"] == 1
        assert result["failed"] == []


def test_cli_serializes_decimal_failure_and_returns_two(tmp_path, monkeypatch, capsys):
    invalid = event("invalid", schemaVersion=Decimal("99"))
    invalid["game_id"] = Decimal("8")
    table = MemoryTable([invalid])
    resource = MagicMock()
    resource.Table.return_value = table
    monkeypatch.setattr(migration, "dynamodb_resource", lambda: resource)

    exit_code = migration.main(
        [
            "--table",
            "cdrl_events_m07_test",
            "--report",
            str(tmp_path / "decimal.json"),
        ]
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert "$decimal" in output.err
    report = json.loads((tmp_path / "decimal.json").read_text(encoding="utf-8"))
    assert report["runs"][0]["failed"] == 1
    assert report["runs"][0]["failureDetails"][0]["game_id"] == {
        "$decimal": "8"
    }


def test_invalid_report_is_rejected_before_table_scan(tmp_path, monkeypatch):
    report_path = tmp_path / "invalid.json"
    report_path.write_text('{"assignmentId":"wrong","runs":[]}', encoding="utf-8")
    table = MagicMock()
    resource = MagicMock()
    resource.Table.return_value = table
    monkeypatch.setattr(migration, "dynamodb_resource", lambda: resource)

    exit_code = migration.main(
        ["--table", "cdrl_events_m07_test", "--report", str(report_path)]
    )

    assert exit_code == 1
    table.scan.assert_not_called()
    table.put_item.assert_not_called()


def test_snapshot_ignores_mapping_order_and_normalizes_decimal_values():
    left = MemoryTable([{"game_id": Decimal("1000"), "event_key": "same", "custom": {"a": 1, "b": 2}}])
    right = MemoryTable([{"custom": {"b": 2, "a": 1}, "event_key": "same", "game_id": Decimal("1E+3")}])

    assert migration._snapshot(left) == migration._snapshot(right)
