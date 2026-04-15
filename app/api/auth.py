from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.user import LoginRequest, Token, UserCreate, UserRead
from app.services.user_service import authenticate_user, create_user
from app.services.audit_service import log_login_success, log_login_failure
from app.core.security import create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=Token)
def login(
    data: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user, error = authenticate_user(db, data.email, data.password)
    if error:
        log_login_failure(db, reason=error, email=data.email, request=request)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas.",
        )

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    log_login_success(db, user_id=user.id, request=request)

    role_names = [role.name for role in user.roles]

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "roles": role_names,
        }
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", response_model=UserRead, status_code=201)
def register(
    data: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = create_user(db, data)
    return user

