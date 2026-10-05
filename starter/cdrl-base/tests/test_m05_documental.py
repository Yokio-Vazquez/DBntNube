import pytest
from pydantic import ValidationError
from botocore.exceptions import BotoCoreError, ClientError

from src.nosql import create_event, get_event, delete_event
from src.schemas import EventDocument

@pytest.fixture(autouse=True)
def setup_teardown():
    yield
    try:
        delete_event(99, "test_event_key")
    except Exception:
        pass

def is_dynamo_unreachable(error):
    return type(error).__name__ in ("ConnectTimeoutError", "EndpointConnectionError", "TimeoutError")

def test_m05_normal_document_creation():
    doc = EventDocument(
        game_id=99,
        event_key="test_event_key",
        event_type="test_type",
        occurred_at="2026-10-04T12:00:00Z",
        source="test"
    )
    try:
        success = create_event(doc)
    except BotoCoreError as e:
        if is_dynamo_unreachable(e):
            pytest.skip("DynamoDB Local is unreachable")
        raise
    
    assert success is True
    
    retrieved = get_event(99, "test_event_key")
    assert retrieved is not None
    assert retrieved["event_type"] == "test_type"

def test_m05_edge_duplicate_idempotency():
    doc = EventDocument(
        game_id=99,
        event_key="test_event_key",
        event_type="test_type",
        occurred_at="2026-10-04T12:00:00Z",
        source="test"
    )
    try:
        create_event(doc)
        success = create_event(doc)
        assert success is False
    except BotoCoreError as e:
        if is_dynamo_unreachable(e):
            pytest.skip("DynamoDB Local is unreachable")
        raise

def test_m05_edge_absence():
    try:
        retrieved = get_event(99, "non_existent_key")
        assert retrieved is None
    except BotoCoreError as e:
        if is_dynamo_unreachable(e):
            pytest.skip("DynamoDB Local is unreachable")
        raise

def test_m05_failure_validation():
    with pytest.raises(ValidationError):
        EventDocument(
            game_id=99,
            event_key="test_event_key",
            event_type="test_type",
            occurred_at="fecha-invalida",
            source="test"
        )
