import os

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

TABLE_NAME = os.getenv("DYNAMODB_TABLE", "cdrl_events")

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
    return boto3.resource("dynamodb", **options)


def ensure_events_table():
    resource = dynamodb_resource()
    client = resource.meta.client
    try:
        client.describe_table(TableName=TABLE_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "game_id", "KeyType": "HASH"},
                {"AttributeName": "event_key", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "game_id", "AttributeType": "N"},
                {"AttributeName": "event_key", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    return resource.Table(TABLE_NAME)


def seed_fixture_events(table):
    for event in FIXTURE_EVENTS:
        table.put_item(Item=event)


def query_events(game_id: int):
    table = dynamodb_resource().Table(TABLE_NAME)
    response = table.query(KeyConditionExpression=Key("game_id").eq(game_id))
    return response.get("Items", [])