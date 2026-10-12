from collections.abc import Mapping

from sqlalchemy import insert
from sqlalchemy.orm import Session

from .models import AuditLog


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