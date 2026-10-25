from copy import deepcopy
from decimal import Decimal
import runpy

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

import src.main as main_module
from src.event_schemas import (
    EventV3, UnsupportedEventVersion, detect_version, downcast_from_v3,
    normalize_event, project, upcast_to_v3,
)
from src.schemas import configured_event_model


@pytest.fixture
def legacy():
    return dict(game_id=1, event_key="synthetic-001", event_type="session_started",
                occurred_at="2026-10-11T10:00:00Z", source="synthetic-fixture")


@pytest.fixture
def mixed(legacy):
    return [legacy, dict(legacy, event_key="synthetic-002", schemaVersion=2),
            dict(legacy, event_key="synthetic-003", schemaVersion=3, platform="pc", metadata={"mode": "solo"})]


@pytest.mark.parametrize("target", [None, 1, 2, 3])
def test_mixed_api(monkeypatch, mixed, target):
    before = deepcopy(mixed)
    monkeypatch.setattr(main_module, "query_events", lambda game_id: mixed)
    params = {"game_id": 1}
    if target is not None:
        params["version"] = target
    with TestClient(main_module.app) as client:
        response = client.get("/events", params=params)
    assert response.status_code == 200
    events = response.json()
    if target is None:
        assert events[:2] == [{**mixed[0], "schemaVersion": 1}, mixed[1]]
        assert events[2] == mixed[2]
    elif target == 3:
        assert all(e["schemaVersion"] == 3 and "platform" in e and "metadata" in e for e in events)
        assert events[0]["platform"] == "unknown"
        assert events[0]["metadata"] == {}
        assert events[2]["metadata"] == {"mode": "solo"}
    else:
        assert all(e["schemaVersion"] == target for e in events)
        assert all(not {"platform", "metadata", "migratedFrom", "migratedVersionExplicit"}.intersection(e) for e in events)
    assert mixed == before


@pytest.mark.parametrize("version", [0, 4, 9, "invalid"])
def test_invalid_api_target(monkeypatch, version):
    def unexpected_query(game_id):
        pytest.fail("Invalid target must not query DynamoDB")
    monkeypatch.setattr(main_module, "query_events", unexpected_query)
    with TestClient(main_module.app) as client:
        assert client.get("/events", params={"game_id": 1, "version": version}).status_code == 422


@pytest.mark.parametrize("target", [None, 2, 3])
def test_unknown_stored_version(monkeypatch, legacy, target):
    monkeypatch.setattr(main_module, "query_events", lambda game_id: [dict(legacy, schemaVersion=99)])
    params = {"game_id": 1}
    if target:
        params["version"] = target
    with TestClient(main_module.app) as client:
        assert client.get("/events", params=params).status_code == 500


@pytest.mark.parametrize("version", [None, 1, 2])
def test_round_trip_and_idempotence(legacy, version):
    if version is not None:
        legacy["schemaVersion"] = version
    legacy["custom"] = {"values": [Decimal("1.25")]}
    before = deepcopy(legacy)
    migrated = upcast_to_v3(legacy)
    assert upcast_to_v3(migrated) == migrated
    assert downcast_from_v3(migrated) == before
    assert legacy == before
    migrated["custom"]["values"].append(2)
    assert legacy == before


def test_native_v3_projection_is_not_rollback(mixed):
    native = mixed[2]
    with pytest.raises(ValueError):
        downcast_from_v3(native)
    projected = project(native, 2)
    assert projected == {**mixed[0], "event_key": "synthetic-003", "schemaVersion": 2}
    assert native["schemaVersion"] == 3


@pytest.mark.parametrize("field,value", [("platform", "pc"), ("metadata", {}), ("migratedFrom", 2), ("migratedVersionExplicit", False)])
def test_legacy_reserved_fields_rejected(legacy, field, value):
    legacy[field] = value
    with pytest.raises(ValueError):
        upcast_to_v3(legacy)


@pytest.mark.parametrize("version", [99, "3", True, None, Decimal("2.5")])
def test_invalid_stored_version(legacy, version):
    with pytest.raises(UnsupportedEventVersion):
        upcast_to_v3(dict(legacy, schemaVersion=version))


def test_dynamodb_decimal_version(legacy):
    assert detect_version(dict(legacy, schemaVersion=Decimal(3))) == 3
    assert normalize_event(dict(legacy, schemaVersion=Decimal(3))).platform == "unknown"


def test_missing_required_field(legacy):
    del legacy["source"]
    with pytest.raises(ValidationError):
        upcast_to_v3(legacy)


def test_defaults_are_independent(legacy):
    first = EventV3(**legacy)
    second = EventV3(**legacy)
    first.metadata["changed"] = True
    assert second.metadata == {}


@pytest.mark.parametrize("version", ["2", "3"])
def test_writer_configuration(monkeypatch, legacy, version):
    monkeypatch.setenv("EVENT_WRITE_VERSION", version)
    model = configured_event_model()
    if version == "3":
        with pytest.raises(ValidationError):
            model(**legacy)
        legacy["platform"] = "pc"
    document = model(**legacy).model_dump(by_alias=True)
    assert document["schemaVersion"] == int(version)
    assert "migratedFrom" not in document
    if version == "2":
        assert document == {**legacy, "schemaVersion": 2}
    else:
        assert document["metadata"] == {}
    with pytest.raises(ValidationError):
        model(**dict(legacy, migratedFrom=2))
    with pytest.raises(ValidationError):
        model(**dict(legacy, platform="invalid"))
    with pytest.raises(ValidationError):
        model(**dict(legacy, schemaVersion=3 if version == "2" else 2))


def test_writer_default(monkeypatch, legacy):
    monkeypatch.delenv("EVENT_WRITE_VERSION", raising=False)
    assert configured_event_model()(**legacy).schema_version == 2


@pytest.mark.parametrize("value", ["1", "9", "", "invalid"])
def test_invalid_configuration_at_import(monkeypatch, value):
    monkeypatch.setenv("EVENT_WRITE_VERSION", value)
    with pytest.raises(ValueError, match="EVENT_WRITE_VERSION debe ser 2 o 3"):
        runpy.run_path("src/schemas.py")


@pytest.mark.parametrize("version", ["2", "3"])
def test_configured_alias_at_import(monkeypatch, legacy, version):
    monkeypatch.setenv("EVENT_WRITE_VERSION", version)
    namespace = runpy.run_path("src/schemas.py")
    if version == "3":
        legacy["platform"] = "mobile"
    assert namespace["EventDocument"](**legacy).schema_version == int(version)


@pytest.mark.parametrize("target", [0, 9, True, "3"])
def test_invalid_projection_target(legacy, target):
    with pytest.raises(UnsupportedEventVersion):
        project(legacy, target)


def test_previously_migrated_v3_rolls_back(legacy):
    migrated = dict(legacy, schemaVersion=3, platform="unknown", metadata={}, migratedFrom=2)
    assert downcast_from_v3(migrated) == dict(legacy, schemaVersion=2)


@pytest.mark.parametrize("version", ["2", "3"])
def test_writer_persists_configured_document(monkeypatch, legacy, version):
    from unittest.mock import MagicMock
    import src.nosql as nosql
    monkeypatch.setenv("EVENT_WRITE_VERSION", version)
    if version == "3":
        legacy["platform"] = "console"
        legacy["metadata"] = {"mode": "cooperative"}
    event = configured_event_model()(**legacy)
    resource = MagicMock()
    monkeypatch.setattr(nosql, "dynamodb_resource", lambda: resource)
    assert nosql.create_event(event) is True
    saved = resource.Table.return_value.put_item.call_args.kwargs["Item"]
    assert saved == dict(legacy, schemaVersion=int(version))
    assert "migratedFrom" not in saved
