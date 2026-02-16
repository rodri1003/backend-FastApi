from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps import require_admin
from app.models.user import User
from app.schemas.user import UserRead

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/ping")
def admin_ping(current_user: User = Depends(require_admin)):
    return {
        "message": "Acceso admin OK",
        "user": current_user.username,
        "role": current_user.role,
    }


@router.get("/users", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    users = db.query(User).all()
    return users
