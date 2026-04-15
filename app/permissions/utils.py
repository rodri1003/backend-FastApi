"""
Utilidades para permisos Casbin.
"""
from __future__ import annotations

from app.models.user import User
from app.permissions.casbin_enforcer import get_enforcer

# Recursos y acciones para el frontend (visibilidad de menús y botones)
RESOURCES = ["users", "roles", "permissions", "audit_logs", "rooms", "reservations", "payments", "dashboard"]
ACTIONS = ["read", "create", "update", "delete"]


def get_user_permissions(user: User) -> list[str]:
    """
    Devuelve lista de permisos efectivos del usuario (resource:action).
    Casbin aplica wildcards (*) automáticamente.
    """
    enforcer = get_enforcer()
    role_names = [r.name for r in user.roles]
    permissions: list[str] = []

    for resource in RESOURCES:
        for action in ACTIONS:
            for role_name in role_names:
                if enforcer.enforce(role_name, resource, action):
                    key = f"{resource}:{action}"
                    if key not in permissions:
                        permissions.append(key)
                    break

    return permissions
