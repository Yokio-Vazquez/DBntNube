"""Permisos de la colección events para identidades de servicio."""
import os
from secrets import compare_digest

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)
ROLE_KEYS = {"reader": "EVENTS_READER_TOKEN", "writer": "EVENTS_WRITER_TOKEN"}
PERMISSIONS = {"reader": {"read"}, "writer": {"read", "create"}}


def event_role(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    token = credentials.credentials.encode() if credentials else b""
    roles = []
    for role, variable in ROLE_KEYS.items():
        configured = os.getenv(variable, "").encode()
        if configured and compare_digest(token, configured):
            roles.append(role)
    if len(roles) != 1:
        raise HTTPException(401, "Credencial inválida", headers={"WWW-Authenticate": "Bearer"})
    return roles[0]


def require_event(operation: str):
    def authorize(role: str = Depends(event_role)):
        if operation not in PERMISSIONS.get(role, set()):
            raise HTTPException(403, "Operación no permitida")
        return role
    return authorize
