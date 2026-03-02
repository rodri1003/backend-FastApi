"""
Servicio de bitácora (audit log).

Registra eventos de autenticación y acciones autorizadas en audit_logs.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def _get_client_ip(request: Any) -> str | None:
    """Obtiene la IP del cliente desde headers o conexión."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return getattr(request.client, "host", None)


def _get_user_agent(request: Any) -> str | None:
    """Obtiene el User-Agent del request."""
    if request is None:
        return None
    return request.headers.get("user-agent")


def log_login_success(
    db: Session,
    user_id: int,
    request: Any | None = None,
) -> AuditLog:
    """Registra login exitoso."""
    entry = AuditLog(
        event_type="login_success",
        user_id=user_id,
        resource=None,
        action=None,
        method="POST",
        path="/auth/login",
        status_code=200,
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
        metadata_json=None,
    )
    db.add(entry)
    db.commit()
    return entry


def log_login_failure(
    db: Session,
    reason: str,
    email: str | None = None,
    request: Any | None = None,
) -> AuditLog:
    """Registra login fallido (credenciales inválidas, usuario inactivo, etc.)."""
    metadata = {}
    if email:
        metadata["email"] = email
    metadata["reason"] = reason

    entry = AuditLog(
        event_type="login_failure",
        user_id=None,
        resource=None,
        action=None,
        method="POST",
        path="/auth/login",
        status_code=401,
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
        metadata_json=json.dumps(metadata),
    )
    db.add(entry)
    db.commit()
    return entry


def log_action(
    db: Session,
    user_id: int,
    resource: str,
    action: str,
    method: str | None = None,
    path: str | None = None,
    status_code: int | None = 200,
    request: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Registra una acción autorizada (acceso a recurso con permiso)."""
    metadata_json = json.dumps(metadata) if metadata else None

    entry = AuditLog(
        event_type="action",
        user_id=user_id,
        resource=resource,
        action=action,
        method=method,
        path=path,
        status_code=status_code,
        ip_address=_get_client_ip(request),
        user_agent=_get_user_agent(request),
        metadata_json=metadata_json,
    )
    db.add(entry)
    db.commit()
    return entry
