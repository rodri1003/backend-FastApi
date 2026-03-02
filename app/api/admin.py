from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserRead
from app.permissions.deps import require_permission

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get(
    "/ping",
    dependencies=[Depends(require_permission("admin", "read"))],
)
def admin_ping(current_user: User = Depends(get_current_user)):
    return {
        "message": "Acceso admin OK",
        "user": current_user.email,
    }


@router.get(
    "/users",
    response_model=list[UserRead],
    dependencies=[Depends(require_permission("admin", "read"))],
)
def list_users(db: Session = Depends(get_db)):
    users = (
        db.query(User)
        .options(
            selectinload(User.roles),
            selectinload(User.profile),
        )
        .all()
    )
    return users
