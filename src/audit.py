from uuid import uuid4
from collections.abc import Mapping

from sqlalchemy import func, insert, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .models import AuditLog, EventAuditOutbox


_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "credential",
    "authorization",
    "apikey",
    "privatekey",
)

EVENT_AUDIT_ACTORS = {"reader", "writer", "anonymous"}
EVENT_AUDIT_ACTIONS = {"read", "create"}
EVENT_AUDIT_OUTCOMES = {
    "success",
    "denied",
    "conflict",
    "unavailable",
    "failure",
}


class AuditPersistenceError(RuntimeError):
    """The event audit record could not be committed."""


class AuditOutboxStateError(RuntimeError):
    """The event audit outbox entry is no longer pending."""


def sanitize_audit_details(value):
    if isinstance(value, Mapping):
        sanitized = {}
        for key, item in value.items():
            normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
            sanitized[str(key)] = (
                "[REDACTED]"
                if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS)
                else sanitize_audit_details(item)
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_audit_details(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return "[REDACTED]"


def record_audit(
    db: Session,
    *,
    actor_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str,
    details: Mapping | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        details=sanitize_audit_details(details or {}),
    )
    db.execute(
        insert(AuditLog.__table__).inline().values(
            actor_id=entry.actor_id,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            outcome=entry.outcome,
            details=entry.details,
        )
    )
    return entry


def record_event_audit(
    db: Session,
    *,
    actor_id: str,
    action: str,
    outcome: str,
    resource_id: str | None = None,
) -> AuditLog:
    if actor_id not in EVENT_AUDIT_ACTORS:
        raise ValueError("Identidad de auditoría de eventos inválida.")
    if action not in EVENT_AUDIT_ACTIONS:
        raise ValueError("Acción de auditoría de eventos inválida.")
    if outcome not in EVENT_AUDIT_OUTCOMES:
        raise ValueError("Resultado de auditoría de eventos inválido.")

    try:
        entry = record_audit(
            db,
            actor_id=actor_id,
            action=action,
            resource_type="events",
            resource_id=resource_id,
            outcome=outcome,
        )
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise AuditPersistenceError(
            "No se pudo confirmar el registro de auditoría de eventos."
        ) from error
    return entry


def begin_event_audit(
    db: Session,
    *,
    actor_id: str,
    game_id: int,
    event_key: str,
) -> str:
    if actor_id != "writer":
        raise ValueError("Identidad de auditoría de eventos inválida.")

    operation_id = uuid4().hex
    try:
        db.execute(
            insert(EventAuditOutbox).values(
                operation_id=operation_id,
                actor_id=actor_id,
                game_id=game_id,
                event_key=event_key,
                status="pending",
            )
        )
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise AuditPersistenceError(
            "No se pudo reservar la operación de auditoría de eventos."
        ) from error
    return operation_id


def complete_event_audit(
    db: Session,
    *,
    operation_id: str,
    actor_id: str,
    game_id: int,
    event_key: str,
    outcome: str,
) -> AuditLog:
    if actor_id != "writer":
        raise ValueError("Identidad de auditoría de eventos inválida.")
    if outcome not in {"success", "conflict", "unavailable", "failure"}:
        raise ValueError("Resultado de auditoría de eventos inválido.")

    try:
        entry = record_audit(
            db,
            actor_id=actor_id,
            action="create",
            resource_type="events",
            resource_id=None,
            outcome=outcome,
            details={"operation_id": operation_id},
        )
        result = db.execute(
            update(EventAuditOutbox)
            .where(
                EventAuditOutbox.operation_id == operation_id,
                EventAuditOutbox.actor_id == actor_id,
                EventAuditOutbox.game_id == game_id,
                EventAuditOutbox.event_key == event_key,
                EventAuditOutbox.status == "pending",
            )
            .values(
                status="completed",
                outcome=outcome,
                completed_at=func.now(),
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise AuditOutboxStateError(
                "La operación de auditoría ya no está pendiente."
            )
        db.commit()
    except AuditOutboxStateError:
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise AuditPersistenceError(
            "No se pudo completar el registro de auditoría de eventos."
        ) from error
    return entry


def reconciled_event_outcome(
    operation_id: str,
    stored_event: Mapping | None,
) -> str:
    if stored_event is None:
        return "unavailable"
    if stored_event.get("_audit_operation_id") == operation_id:
        return "success"
    return "conflict"