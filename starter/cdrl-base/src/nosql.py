import os
import time

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from botocore.config import Config
from dotenv import load_dotenv
from .schemas import EventDocument

load_dotenv()

TABLE_NAME = os.getenv("DYNAMODB_TABLE", "cdrl_events")
EVENT_TYPE_INDEX = "event-type-occurred-at-index"

TABLE_KEY_SCHEMA = [
    {"AttributeName": "game_id", "KeyType": "HASH"},
    {"AttributeName": "event_key", "KeyType": "RANGE"},
]
ATTRIBUTE_DEFINITIONS = [
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
            GlobalSecondaryIndexes=[EVENT_TYPE_INDEX_DEFINITION],
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=TABLE_NAME)
        table_description = client.describe_table(TableName=TABLE_NAME)["Table"]

    client.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    indexes = table_description.get("GlobalSecondaryIndexes", [])
    if not any(index["IndexName"] == EVENT_TYPE_INDEX for index in indexes):
        client.update_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=ATTRIBUTE_DEFINITIONS,
            GlobalSecondaryIndexUpdates=[{"Create": EVENT_TYPE_INDEX_DEFINITION}],
        )

    for _ in range(30):
        table_description = client.describe_table(TableName=TABLE_NAME)["Table"]
        indexes = table_description.get("GlobalSecondaryIndexes", [])
        if any(
            index["IndexName"] == EVENT_TYPE_INDEX
            and index.get("IndexStatus") == "ACTIVE"
            for index in indexes
        ):
            break
        time.sleep(1)
    else:
        raise TimeoutError(f"DynamoDB index {EVENT_TYPE_INDEX} did not become active")

    return resource.Table(TABLE_NAME)


def seed_fixture_events(table):
    for event in FIXTURE_EVENTS:
        table.put_item(Item=event)


def query_events(game_id: int):
    table = dynamodb_resource().Table(TABLE_NAME)
    response = table.query(KeyConditionExpression=Key("game_id").eq(game_id))
    return response.get("Items", [])

def create_event(event: EventDocument) -> bool:
    table = dynamodb_resource().Table(TABLE_NAME)

    try:
        table.put_item(
            Item=event.model_dump(),
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
    response = table.query(
        IndexName=EVENT_TYPE_INDEX,
        KeyConditionExpression=(
            Key("event_type").eq(event_type)
            & Key("occurred_at").between(from_time, to_time)
        ),
    )
    return response.get("Items", [])


def update_event(
    game_id: int,
    event_key: str,
    event: EventDocument,
) -> dict:
    if event.game_id != game_id or event.event_key != event_key:
        raise ValueError("Las claves del evento no pueden cambiar.")

    fields = event.model_dump(exclude={"game_id", "event_key"})
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