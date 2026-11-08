"""Permisos de la colección events para identidades de servicio."""
import os
from secrets import compare_digest

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .audit import AuditPersistenceError, record_event_audit
from .database import get_db_writer

bearer = HTTPBearer(auto_error=False)
ROLE_KEYS = {"reader": "EVENTS_READER_TOKEN", "writer": "EVENTS_WRITER_TOKEN"}
PERMISSIONS = {"reader": {"read"}, "writer": {"read", "create"}}


def _request_action(request: Request) -> str:
    return "create" if request.method == "POST" else "read"


def _audit_auth_result(
    db: Session,
    *,
    actor: str,
    action: str,
) -> None:
    try:
        record_event_audit(
            db,
            actor_id=actor,
            action=action,
            outcome="denied",
        )
    except AuditPersistenceError as error:
        raise HTTPException(503, "Auditoría no disponible") from error


def event_role(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db_writer),
):
    token = credentials.credentials.encode() if credentials else b""
    roles = []
    for role, variable in ROLE_KEYS.items():
        configured = os.getenv(variable, "").encode()
        if configured and compare_digest(token, configured):
            roles.append(role)
    if len(roles) != 1:
        _audit_auth_result(
            db,
            actor="anonymous",
            action=_request_action(request),
        )
        raise HTTPException(401, "Credencial inválida", headers={"WWW-Authenticate": "Bearer"})
    return roles[0]


def require_event(operation: str):
    def authorize(
        request: Request,
        role: str = Depends(event_role),
        db: Session = Depends(get_db_writer),
    ):
        if operation not in PERMISSIONS.get(role, set()):
            _audit_auth_result(
                db,
                actor=role,
                action=_request_action(request),
            )
            raise HTTPException(403, "Operación no permitida")
        return role
    return authorize
