"""
Módulo de usuarios. 

"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserMeRead, UserProfileUpdate
from app.services.audit_service import log_action
from app.services.user_service import update_user_profile
from app.permissions.utils import get_user_permissions

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserMeRead)
def read_current_user(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log_action(
        db,
        user_id=current_user.id,
        resource="profile",
        action="read",
        method="GET",
        path="/users/me",
        status_code=200,
        request=request,
    )
    permissions = get_user_permissions(current_user)
    return UserMeRead(
        id=current_user.id,
        email=current_user.email,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        roles=current_user.roles,
        profile=current_user.profile,
        permissions=permissions,
    )


@router.put("/me", response_model=UserMeRead)
def update_current_user_profile(
    data: UserProfileUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated_user = update_user_profile(db, current_user.id, data)
    log_action(
        db,
        user_id=current_user.id,
        resource="profile",
        action="update",
        method="PUT",
        path="/users/me",
        status_code=200,
        request=request,
    )
    permissions = get_user_permissions(updated_user)
    return UserMeRead(
        id=updated_user.id,
        email=updated_user.email,
        is_active=updated_user.is_active,
        is_verified=updated_user.is_verified,
        roles=updated_user.roles,
        profile=updated_user.profile,
        permissions=permissions,
    )

