from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.permissions.casbin_enforcer import get_enforcer
from app.services.audit_service import log_action


def require_permission(resource: str, action: str):
    """
    Dependencia reutilizable para autorización basada en permisos.
    Registra la acción en bitácora cuando el permiso es concedido.
    """

    def _checker(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        enforcer = get_enforcer()

        db.refresh(current_user)
        role_names = [role.name for role in current_user.roles]

        for role_name in role_names:
            if enforcer.enforce(role_name, resource, action):
                log_action(
                    db,
                    user_id=current_user.id,
                    resource=resource,
                    action=action,
                    method=request.method if request else None,
                    path=str(request.url.path) if request else None,
                    status_code=200,
                    request=request,
                )
                return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para acceder a este recurso.",
        )

    return _checker

