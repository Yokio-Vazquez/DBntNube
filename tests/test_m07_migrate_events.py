import json
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

import scripts.migrate_events as migration
from scripts.migrate_events import (
    _record_run,
    migrate_table,
    rollback_table,
)
from src.event_schemas import upcast_to_v3


def event(key, **fields):
    return {
        "game_id": 1,
        "event_key": key,
        "event_type": "session_started",
        "occurred_at": "2026-10-25T10:00:00Z",
        "source": "synthetic-fixture",
        **fields,
    }


def paged_table(pages):
    table = MagicMock()
    table.scan.side_effect = pages
    return table


def test_migrate_dry_run_is_paged_and_does_not_write():
    table = paged_table(
        [
            {
                "Items": [event("v1"), event("v2", schemaVersion=2)],
                "LastEvaluatedKey": {"game_id": 1, "event_key": "v2"},
            },
            {
                "Items": [
                    event("native", schemaVersion=3, platform="pc", metadata={}),
                    event("unknown", schemaVersion=99),
                    {"game_id": 1, "event_key": "missing-source"},
                ]
            },
        ]
    )

    result = migrate_table(table, dry_run=True)

    assert result["scanned"] == 5
    assert result["migrated"] == 2
    assert result["skipped"] == 1
    assert len(result["failed"]) == 2
    assert table.scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {
        "game_id": 1,
        "event_key": "v2",
    }
    table.put_item.assert_not_called()


def test_migrate_writes_with_a_conditional_expression():
    table = paged_table([{"Items": [event("v1")]}])

    result = migrate_table(table)

    assert result["migrated"] == 1
    saved_item = table.put_item.call_args.kwargs["Item"]
    assert saved_item["schemaVersion"] == 3
    assert saved_item["migratedFrom"] == 1
    assert table.put_item.call_args.kwargs["ConditionExpression"] is not None


def test_concurrent_migration_is_counted_as_skipped():
    table = paged_table([{"Items": [event("already-migrated-by-another-worker")]}])
    table.put_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException",
                "Message": "The document was already migrated",
            }
        },
        "PutItem",
    )

    result = migrate_table(table)

    assert result["migrated"] == 0
    assert result["skipped"] == 1
    assert result["failed"] == []


def test_rollback_only_reverts_documents_marked_as_migrated():
    migrated_v1 = upcast_to_v3(event("migrated-v1"))
    native_v3 = event("native-v3", schemaVersion=3, platform="pc", metadata={})
    legacy_v2 = event("legacy-v2", schemaVersion=2)
    invalid = event("invalid", schemaVersion=99)
    table = paged_table(
        [{"Items": [migrated_v1, native_v3, legacy_v2, invalid]}]
    )

    result = rollback_table(table)

    assert result["scanned"] == 4
    assert result["rolledBack"] == 1
    assert result["skipped"] == 2
    assert len(result["failed"]) == 1
    restored = table.put_item.call_args.kwargs["Item"]
    assert restored == event("migrated-v1")
    assert table.put_item.call_args.kwargs["ConditionExpression"] is not None


def test_report_accumulates_runs_and_verifies_repeatability_and_rollback(tmp_path):
    report_path = tmp_path / "results.json"
    first_migration = {
        "operation": "migrate",
        "scanned": 7,
        "migrated": 4,
        "skipped": 2,
        "failed": [{"event_key": "invalid", "reason": "unsupported version"}],
        "durationSeconds": 0.01,
    }
    second_migration = {
        **first_migration,
        "migrated": 0,
        "skipped": 6,
    }
    rollback = {
        "operation": "rollback",
        "scanned": 7,
        "rolledBack": 5,
        "skipped": 1,
        "failed": [{"event_key": "invalid", "reason": "unsupported version"}],
        "durationSeconds": 0.01,
    }

    _record_run(report_path, "cdrl_events_m07_test", first_migration, False)
    _record_run(report_path, "cdrl_events_m07_test", second_migration, False)
    report = _record_run(report_path, "cdrl_events_m07_test", rollback, False)

    assert len(report["runs"]) == 3
    assert report["idempotent"] is True
    assert report["rollbackVerified"] is True
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_cli_returns_two_when_invalid_documents_are_reported(tmp_path, monkeypatch):
    table = paged_table([{"Items": [event("invalid", schemaVersion=99)]}])
    resource = MagicMock()
    resource.Table.return_value = table
    monkeypatch.setattr(migration, "dynamodb_resource", lambda: resource)

    exit_code = migration.main(
        ["--table", "cdrl_events_m07_test", "--report", str(tmp_path / "results.json")]
    )

    assert exit_code == 2
