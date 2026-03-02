from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserRead
from app.services.user_service import create_user
from app.services.audit_service import log_action

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/register", response_model=UserRead, status_code=201)
def register_user(
    user_in: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = create_user(db, user_in)
    log_action(
        db,
        user_id=user.id,
        resource="auth",
        action="register",
        method="POST",
        path="/users/register",
        status_code=201,
        request=request,
    )
    return user


@router.get("/me", response_model=UserRead)
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
    return current_user
