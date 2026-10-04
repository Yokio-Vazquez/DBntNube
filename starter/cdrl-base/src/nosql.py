import os
import time

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from botocore.config import Config
from dotenv import load_dotenv

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