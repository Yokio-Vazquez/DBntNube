import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError
from botocore.exceptions import BotoCoreError, ClientError

from src.nosql import create_event, get_event, delete_event
from src.schemas import EventDocument


@pytest.fixture(autouse=True)
def cleanup_test_event():
    """Limpia el evento de prueba después de cada test."""
    yield
    try:
        delete_event(99, "test_event_key")
    except Exception:
        pass


def _make_table_mock():
    """Helper: devuelve un mock de la tabla DynamoDB resource."""
    mock_resource = MagicMock()
    mock_table = MagicMock()
    mock_resource.Table.return_value = mock_table
    return mock_resource, mock_table


# ── Caso Normal ─────────────────────────────────────────────────
def test_m05_normal_document_creation():
    """
    Normal: Crear un documento y verificar que se puede recuperar.
    Usa mock para no depender de que DynamoDB esté corriendo.
    """
    doc = EventDocument(
        game_id=99,
        event_key="test_event_key",
        event_type="test_type",
        occurred_at="2026-10-04T12:00:00Z",
        source="test",
    )
    mock_item = doc.model_dump(by_alias=True)

    mock_resource, mock_table = _make_table_mock()
    # Primera llamada (get_item en create_event): no existe
    mock_table.get_item.return_value = {}
    mock_table.put_item.return_value = {}

    with patch("src.nosql.dynamodb_resource", return_value=mock_resource):
        success = create_event(doc)
        assert success is True

        # Segunda llamada (get_item en get_event): existe
        mock_table.get_item.return_value = {"Item": mock_item}
        retrieved = get_event(99, "test_event_key")

    assert retrieved is not None
    assert retrieved["event_type"] == "test_type"


# ── Caso límite: Idempotencia (duplicado) ─────────────────────
def test_m05_edge_duplicate_idempotency():
    """
    Límite: Insertar el mismo documento dos veces NO debe crear duplicados.
    La segunda inserción debe retornar False (ConditionalCheckFailedException).
    """
    doc = EventDocument(
        game_id=99,
        event_key="test_event_key",
        event_type="test_type",
        occurred_at="2026-10-04T12:00:00Z",
        source="test",
    )
    mock_resource, mock_table = _make_table_mock()

    with patch("src.nosql.dynamodb_resource", return_value=mock_resource):
        # Primera inserción exitosa
        mock_table.put_item.return_value = {}
        first = create_event(doc)
        assert first is True

        # Segunda inserción: simular ConditionalCheckFailedException
        error = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "The conditional request failed"}},
            "PutItem",
        )
        mock_table.put_item.side_effect = error
        second = create_event(doc)
        assert second is False


# ── Caso límite: Ausencia ───────────────────────────────────────
def test_m05_edge_absence():
    """
    Límite: Consultar un documento inexistente debe retornar None.
    """
    mock_resource, mock_table = _make_table_mock()
    mock_table.get_item.return_value = {}  # Sin "Item" = no existe

    with patch("src.nosql.dynamodb_resource", return_value=mock_resource):
        retrieved = get_event(99, "non_existent_key")

    assert retrieved is None


# ── Fallo declarado: Validación de esquema ─────────────────────
def test_m05_failure_validation():
    """
    Fallo declarado: Un documento con formato de fecha inválido debe ser
    rechazado por Pydantic antes de llegar a DynamoDB.
    """
    with pytest.raises(ValidationError):
        EventDocument(
            game_id=99,
            event_key="test_event_key",
            event_type="test_type",
            occurred_at="fecha-invalida",
            source="test",
        )


# ── Fallo declarado: DynamoDB inaccesible ─────────────────────
def test_m05_failure_dynamodb_unreachable():
    """
    Fallo declarado: Si DynamoDB lanza BotoCoreError, create_event
    debe propagar la excepción — NUNCA omitir la prueba con skip.
    Un servicio caído DEBE producir fallo de prueba real.
    """
    doc = EventDocument(
        game_id=99,
        event_key="test_event_key",
        event_type="test_type",
        occurred_at="2026-10-04T12:00:00Z",
        source="test",
    )
    mock_resource, mock_table = _make_table_mock()
    mock_table.put_item.side_effect = BotoCoreError()

    with patch("src.nosql.dynamodb_resource", return_value=mock_resource):
        with pytest.raises(BotoCoreError):
            create_event(doc)
