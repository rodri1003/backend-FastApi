"""
Schemas para el módulo admin: roles, permisos, bitácora.
"""
from datetime import datetime

from pydantic import BaseModel, Field


class PolicyRead(BaseModel):
    """Política Casbin: sub (rol), obj (recurso), act (acción)."""
    sub: str
    obj: str
    act: str


class PolicyCreate(BaseModel):
    """Crear política Casbin p(sub, obj, act)."""
    sub: str = Field(..., min_length=1, max_length=255)
    obj: str = Field(..., min_length=1, max_length=255)
    act: str = Field(..., min_length=1, max_length=255)


class AuditLogRead(BaseModel):
    id: int
    event_type: str
    user_id: int | None
    resource: str | None
    action: str | None
    method: str | None
    path: str | None
    status_code: int | None
    ip_address: str | None
    metadata_json: str | None
    created_at: datetime

    class Config:
        from_attributes = True
