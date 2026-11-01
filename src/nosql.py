import os
import time

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from botocore.config import Config
from dotenv import load_dotenv
from .schemas import EventDocument
from .pagination import encode_cursor, decode_cursor, time_key

load_dotenv()

TABLE_NAME = os.getenv("DYNAMODB_TABLE", "cdrl_events")
GAME_TIME_INDEX = "game-occurred-at-index"
GAME_TIME_INDEX_DEFINITION = {
    "IndexName": GAME_TIME_INDEX,
    "KeySchema": [{"AttributeName": "game_id", "KeyType": "HASH"},
                  {"AttributeName": "game_time_key", "KeyType": "RANGE"}],
    "Projection": {"ProjectionType": "ALL"},
}

EVENT_TYPE_INDEX = "event-type-occurred-at-index"

TABLE_KEY_SCHEMA = [
    {"AttributeName": "game_id", "KeyType": "HASH"},
    {"AttributeName": "event_key", "KeyType": "RANGE"},
]
ATTRIBUTE_DEFINITIONS = [
    {"AttributeName": "game_time_key", "AttributeType": "S"},
    {"AttributeName": "game_id", "AttributeType": "N"},
    {"AttributeName": "event_key", "AttributeType": "S"},
    {"AttributeName": "event_type", "AttributeType": "S"},
    {"AttributeName": "occurred_at", "AttributeType": "S"},
]
EVENT_TYPE_INDEX_DEFINITION = {
    "IndexName": EVENT_TYPE_INDEX,
    "KeySchema": [
        {"AttributeName": "event_type", "KeyType": "HASH"},
        {"AttributeName": "occurred_at", "KeyType": "RANGE"},
    ],
    "Projection": {"ProjectionType": "ALL"},
}

GLOBAL_SECONDARY_INDEXES = [EVENT_TYPE_INDEX_DEFINITION, GAME_TIME_INDEX_DEFINITION]

FIXTURE_EVENTS = [
    {
        "game_id": 1,
        "event_key": "session_started#2026-09-27T10:00:00Z#fixture-001",
        "event_type": "session_started",
        "occurred_at": "2026-09-27T10:00:00Z",
        "source": "synthetic-fixture",
    },
    {
        "game_id": 1,
        "event_key": "achievement_unlocked#2026-09-27T10:05:00Z#fixture-002",
        "event_type": "achievement_unlocked",
        "occurred_at": "2026-09-27T10:05:00Z",
        "source": "synthetic-fixture",
    },
    {
        "game_id": 2,
        "event_key": "session_started#2026-09-27T10:10:00Z#fixture-003",
        "event_type": "session_started",
        "occurred_at": "2026-09-27T10:10:00Z",
        "source": "synthetic-fixture",
    },
]

def dynamodb_resource():
    options = {
        "region_name": os.getenv("AWS_REGION", "us-east-1"),
        "endpoint_url": os.getenv("DYNAMODB_ENDPOINT_URL") or None,
    }
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    if access_key and secret_key:
        options["aws_access_key_id"] = access_key
        options["aws_secret_access_key"] = secret_key
        session_token = os.getenv("AWS_SESSION_TOKEN")
        if session_token:
            options["aws_session_token"] = session_token
    config = Config(connect_timeout=5, read_timeout=5, retries={'max_attempts': 0})
    return boto3.resource("dynamodb", config=config, **options)


def ensure_events_table():
    resource = dynamodb_resource()
    client = resource.meta.client
    try:
        table_description = client.describe_table(TableName=TABLE_NAME)["Table"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=TABLE_KEY_SCHEMA,
            AttributeDefinitions=ATTRIBUTE_DEFINITIONS,
            GlobalSecondaryIndexes=GLOBAL_SECONDARY_INDEXES,
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=TABLE_NAME)
        table_description = client.describe_table(TableName=TABLE_NAME)["Table"]

    for definition in GLOBAL_SECONDARY_INDEXES:
        for _ in range(120):
            description = client.describe_table(TableName=TABLE_NAME)["Table"]
            indexes = description.get("GlobalSecondaryIndexes", [])
            existing = next((i for i in indexes if i["IndexName"] == definition["IndexName"]), None)
            if existing and existing.get("IndexStatus") == "ACTIVE":
                break
            if existing is None and description["TableStatus"] == "ACTIVE" and all(
                i.get("IndexStatus") == "ACTIVE" for i in indexes
            ):
                names = {k["AttributeName"] for k in definition["KeySchema"]}
                client.update_table(
                    TableName=TABLE_NAME,
                    AttributeDefinitions=[a for a in ATTRIBUTE_DEFINITIONS if a["AttributeName"] in names],
                    GlobalSecondaryIndexUpdates=[{"Create": definition}],
                )
            time.sleep(1)
        else:
            raise TimeoutError(f"DynamoDB index {definition['IndexName']} did not become active")

    # Backfill existing documents without changing their public schema. Run with writers stopped.
    table = resource.Table(TABLE_NAME)
    for item in _query_all(table.scan):
        expected = time_key(item)
        if item.get("game_time_key") != expected:
            table.update_item(
                Key={"game_id": item["game_id"], "event_key": item["event_key"]},
                UpdateExpression="SET game_time_key = :key",
                ConditionExpression="attribute_exists(game_id) AND occurred_at = :time",
                ExpressionAttributeValues={":key": expected, ":time": item["occurred_at"]},
            )

    return resource.Table(TABLE_NAME)


def seed_fixture_events(table):
    for event in FIXTURE_EVENTS:
        table.put_item(Item=with_time_key(event))


def query_events(game_id: int):
    table = dynamodb_resource().Table(TABLE_NAME)
    return _query_all(table.query, KeyConditionExpression=Key("game_id").eq(game_id))

def create_event(event: EventDocument) -> bool:
    table = dynamodb_resource().Table(TABLE_NAME)

    try:
        table.put_item(
            Item=with_time_key(event.model_dump(by_alias=True)),
            ConditionExpression=(
                Attr("game_id").not_exists()
                & Attr("event_key").not_exists()
            ),
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def get_event(game_id: int, event_key: str) -> dict | None:
    table = dynamodb_resource().Table(TABLE_NAME)
    response = table.get_item(
        Key={"game_id": game_id, "event_key": event_key}
    )
    return response.get("Item")


def query_events_by_type(
    event_type: str,
    from_time: str,
    to_time: str,
) -> list[dict]:
    table = dynamodb_resource().Table(TABLE_NAME)
    return _query_all(
        table.query, IndexName=EVENT_TYPE_INDEX,
        KeyConditionExpression=(
            Key("event_type").eq(event_type)
            & Key("occurred_at").between(from_time, to_time)
        ),
    )


def update_event(
    game_id: int,
    event_key: str,
    event: EventDocument,
) -> dict:
    if event.game_id != game_id or event.event_key != event_key:
        raise ValueError("Las claves del evento no pueden cambiar.")

    fields = event.model_dump(exclude={"game_id", "event_key"}, by_alias=True)
    fields["game_time_key"] = time_key(event.model_dump())
    names = {f"#{name}": name for name in fields}
    values = {f":{name}": value for name, value in fields.items()}
    update_expression = "SET " + ", ".join(
        f"#{name} = :{name}" for name in fields
    )

    table = dynamodb_resource().Table(TABLE_NAME)
    response = table.update_item(
        Key={"game_id": game_id, "event_key": event_key},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ConditionExpression=(
            Attr("game_id").exists() & Attr("event_key").exists()
        ),
        ReturnValues="ALL_NEW",
    )
    return response["Attributes"]


def delete_event(game_id: int, event_key: str) -> bool:
    table = dynamodb_resource().Table(TABLE_NAME)
    response = table.delete_item(
        Key={"game_id": game_id, "event_key": event_key},
        ReturnValues="ALL_OLD",
    )
    return "Attributes" in response

def with_time_key(item):
    return {**item, "game_time_key": time_key(item)}


def _query_all(operation, **kwargs):
    items = []
    while True:
        response = operation(**kwargs)
        items.extend(response.get("Items", []))
        key = response.get("LastEvaluatedKey")
        if not key:
            return items
        kwargs["ExclusiveStartKey"] = key


def query_events_page(game_id: int, limit: int, cursor: str | None = None, *, table=None) -> dict:
    if type(game_id) is not int or game_id <= 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("game_id y limit fuera de rango")
    start = decode_cursor(cursor, game_id) if cursor is not None else None
    table = table if table is not None else dynamodb_resource().Table(TABLE_NAME)
    items, scanned = [], 0
    while len(items) < limit + 1:
        kwargs = dict(IndexName=GAME_TIME_INDEX,
                      KeyConditionExpression=Key("game_id").eq(game_id),
                      ScanIndexForward=False, Limit=limit + 1 - len(items))
        if start:
            kwargs["ExclusiveStartKey"] = start
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))
        scanned += response.get("ScannedCount", 0)
        start = response.get("LastEvaluatedKey")
        if not start:
            break
    return {"items": items[:limit], "scannedCount": scanned,
            "nextCursor": encode_cursor(items[limit-1]) if len(items) > limit else None}
