"""M08 Persona 1: cursor, API and DynamoDB pagination contracts without Docker."""
import base64
import json
from decimal import Decimal

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

import src.main as api
import src.nosql as nosql
from src.pagination import InvalidCursor, decode_cursor, encode_cursor, time_key


def event(key="a", **extra):
    return dict(game_id=1, event_key=key, occurred_at="2026-11-01T10:00:00Z",
                event_type="session_started", source="synthetic-fixture", **extra)


class Pages:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.pages)


def test_cursor_round_trip_and_decimal():
    item = dict(event("ñ"), game_id=Decimal(1))
    assert decode_cursor(encode_cursor(item), 1) == {
        "game_id": 1, "event_key": "ñ", "game_time_key": time_key(item)}


def encoded(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.mark.parametrize("cursor", ["!", "e30", "ew", "x" * 4097,
    encoded(dict(event(), v=2)), encoded(dict(event(), v=True)),
    encoded({"v": 1, "game_id": True, "occurred_at": "x", "event_key": "a"}),
    encoded({"v": 1, "game_id": 1, "occurred_at": "bad", "event_key": "a"}),
    encoded([])])
def test_invalid_cursor(cursor):
    with pytest.raises(InvalidCursor):
        decode_cursor(cursor, 1)


def test_other_game_cursor():
    with pytest.raises(InvalidCursor):
        decode_cursor(encode_cursor(event()), 2)


def test_chronological_key_breaks_ties():
    assert time_key(event("b")) > time_key(event("a"))
    assert time_key(dict(event("z"), occurred_at="2026-10-31T10:00:00Z")) < time_key(event("a"))


def test_full_queries_follow_all_pages(monkeypatch):
    for operation, args in [(nosql.query_events, (1,)),
                            (nosql.query_events_by_type, ("session_started", "a", "z"))]:
        table = Pages([{"Items": [event("a")], "LastEvaluatedKey": {"k": "a"}},
                       {"Items": [event("b")], "LastEvaluatedKey": {"k": "b"}},
                       {"Items": [event("c")]}])
        resource = type("Resource", (), {"Table": lambda self, name: table})()
        monkeypatch.setattr(nosql, "dynamodb_resource", lambda: resource)
        assert [i["event_key"] for i in operation(*args)] == ["a", "b", "c"]
        assert table.calls[1]["ExclusiveStartKey"] == {"k": "a"}


def test_lookahead_refills_short_service_pages():
    table = Pages([{"Items": [event("d")], "ScannedCount": 1,
                    "LastEvaluatedKey": {"k": "d"}},
                   {"Items": [event("c"), event("b")], "ScannedCount": 2}])
    page = nosql.query_events_page(1, 2, table=table)
    assert [i["event_key"] for i in page["items"]] == ["d", "c"]
    assert page["scannedCount"] == 3
    assert decode_cursor(page["nextCursor"], 1)["event_key"] == "c"
    assert [c["Limit"] for c in table.calls] == [3, 2]
    following = Pages([{"Items": [event("b")]}])
    assert nosql.query_events_page(1, 2, page["nextCursor"], table=following)["nextCursor"] is None
    assert following.calls[0]["ExclusiveStartKey"]["event_key"] == "c"


@pytest.mark.parametrize("count", [0, 1, 2])
def test_final_page_has_no_cursor_even_with_service_continuation(count):
    table = Pages([{"Items": [event(str(i)) for i in range(count)],
                    "LastEvaluatedKey": {"k": "last"}}, {"Items": []}])
    assert nosql.query_events_page(1, 2, table=table)["nextCursor"] is None


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"game_id": 0}, {"version": 9}])
def test_api_validation(params, monkeypatch):
    monkeypatch.setattr(api, "query_events_page", lambda *a: pytest.fail("must not query"))
    with TestClient(api.app) as client:
        assert client.get("/events/page", params={"game_id": 1, **params}).status_code == 422


@pytest.mark.parametrize("cursor", ["!", encode_cursor(event())])
def test_api_invalid_cursor(cursor):
    with TestClient(api.app) as client:
        assert client.get("/events/page", params={"game_id": 2, "cursor": cursor}).status_code == 400


@pytest.mark.parametrize("version", [None, 1, 2, 3])
def test_api_projects_and_hides_storage_key(monkeypatch, version):
    monkeypatch.setattr(api, "query_events_page", lambda *a: {
        "items": [nosql.with_time_key(event())], "nextCursor": None, "scannedCount": 1})
    params = {"game_id": 1}
    if version:
        params["version"] = version
    with TestClient(api.app) as client:
        response = client.get("/events/page", params=params)
        assert response.status_code == 200
        body = response.json()
    assert set(body) == {"items", "nextCursor", "limit", "order"}
    assert "game_time_key" not in body["items"][0]
    assert body["items"][0]["schemaVersion"] == (version or 1)


def test_api_failure_codes(monkeypatch):
    def unavailable(*args):
        raise EndpointConnectionError(endpoint_url="http://invalid")
    monkeypatch.setattr(api, "query_events_page", unavailable)
    with TestClient(api.app) as client:
        assert client.get("/events/page?game_id=1").status_code == 503
        monkeypatch.setattr(api, "query_events_page", lambda *a: {
            "items": [event(schemaVersion=99)], "nextCursor": None})
        assert client.get("/events/page?game_id=1").status_code == 500


@pytest.mark.parametrize("default,maximum", [("a", "100"), ("0", "100"), ("50", "25"), ("1", "1001")])
def test_invalid_startup_limits(monkeypatch, default, maximum):
    monkeypatch.setenv("EVENTS_PAGE_DEFAULT_LIMIT", default)
    monkeypatch.setenv("EVENTS_PAGE_MAX_LIMIT", maximum)
    with pytest.raises(ValueError, match="EVENTS_PAGE"):
        api.pagination_limits()


def test_insertions_and_ties_across_cursor_pages():
    class IndexedTable:
        def __init__(self):
            self.items = [nosql.with_time_key(event(str(i).zfill(3))) for i in range(60)]

        def query(self, **kwargs):
            items = sorted(self.items, key=lambda i: i["game_time_key"], reverse=True)
            if "ExclusiveStartKey" in kwargs:
                boundary = kwargs["ExclusiveStartKey"]["game_time_key"]
                items = [i for i in items if i["game_time_key"] < boundary]
            selected = items[:kwargs["Limit"]]
            result = {"Items": selected, "ScannedCount": len(selected)}
            if len(items) > len(selected):
                result["LastEvaluatedKey"] = decode_cursor(encode_cursor(selected[-1]), 1)
            return result

    table = IndexedTable()
    page = nosql.query_events_page(1, 25, table=table)
    seen = [i["event_key"] for i in page["items"]]
    table.items += [nosql.with_time_key(dict(event("new"), occurred_at="2026-11-02T10:00:00Z")),
                    nosql.with_time_key(dict(event("old"), occurred_at="2026-10-31T10:00:00Z"))]
    while page["nextCursor"]:
        page = nosql.query_events_page(1, 25, page["nextCursor"], table=table)
        seen.extend(i["event_key"] for i in page["items"])
    assert len(seen) == len(set(seen)) == 61
    assert "new" not in seen and "old" in seen
    assert {str(i).zfill(3) for i in range(60)} <= set(seen)


def test_create_and_update_maintain_storage_key(monkeypatch):
    from unittest.mock import MagicMock
    from src.schemas import EventDocument
    resource = MagicMock()
    table = resource.Table.return_value
    monkeypatch.setattr(nosql, "dynamodb_resource", lambda: resource)
    doc = EventDocument(**event())
    assert nosql.create_event(doc)
    assert table.put_item.call_args.kwargs["Item"]["game_time_key"] == time_key(event())
    nosql.update_event(1, "a", doc)
    assert table.update_item.call_args.kwargs["ExpressionAttributeValues"][":game_time_key"] == time_key(event())


@pytest.mark.parametrize("existing", [[], [nosql.EVENT_TYPE_INDEX],
                                    [nosql.EVENT_TYPE_INDEX, nosql.GAME_TIME_INDEX]])
def test_ensure_adds_missing_indexes_and_backfills(monkeypatch, existing):
    from unittest.mock import MagicMock
    resource = MagicMock()
    client = resource.meta.client
    table = resource.Table.return_value
    indexes = [{"IndexName": name, "IndexStatus": "ACTIVE"} for name in existing]
    client.describe_table.side_effect = lambda **kw: {
        "Table": {"TableStatus": "ACTIVE", "GlobalSecondaryIndexes": list(indexes)}}

    def add_index(**kwargs):
        updates = kwargs["GlobalSecondaryIndexUpdates"]
        assert len(updates) == 1
        definition = updates[0]["Create"]
        assert {a["AttributeName"] for a in kwargs["AttributeDefinitions"]} == {
            k["AttributeName"] for k in definition["KeySchema"]}
        indexes.append({"IndexName": definition["IndexName"], "IndexStatus": "ACTIVE"})

    client.update_table.side_effect = add_index
    table.scan.side_effect = [{"Items": [event()], "LastEvaluatedKey": {"k": "a"}},
                              {"Items": [nosql.with_time_key(event("b"))]}]
    monkeypatch.setattr(nosql, "dynamodb_resource", lambda: resource)
    monkeypatch.setattr(nosql.time, "sleep", lambda _: None)
    assert nosql.ensure_events_table() is table
    assert client.update_table.call_count == 2 - len(existing)
    assert table.scan.call_args.kwargs["ExclusiveStartKey"] == {"k": "a"}
    table.update_item.assert_called_once()
    backfill = table.update_item.call_args.kwargs
    assert backfill["ExpressionAttributeValues"][":key"] == time_key(event())
    assert "attribute_exists(game_id)" in backfill["ConditionExpression"]
