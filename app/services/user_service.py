from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.core.security import hash_password, verify_password
from app.models.user import Role, User, UserProfile
from app.schemas.user import UserCreate


def create_user(db: Session, user_in: UserCreate) -> User:
    exists_email = db.query(User).filter(User.email == user_in.email).first()
    if exists_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email ya existe.",
        )

    user = User(
        email=user_in.email,
        password_hash=hash_password(user_in.password),
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.flush()

    profile = UserProfile(
        user_id=user.id,
        first_name=user_in.first_name,
        last_name=user_in.last_name,
        phone=user_in.phone,
        avatar_url=user_in.avatar_url,
        date_of_birth=user_in.date_of_birth,
    )
    db.add(profile)

    # Rol por defecto "user" (si existe; el seed lo crea al arrancar)
    default_role = db.query(Role).filter(Role.name == "user").first()
    if default_role is not None:
        user.roles.append(default_role)

    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> tuple[User | None, str | None]:
    """
    Autentica usuario por email y contraseña.

    Returns:
        (user, None) si OK
        (None, "not_found" | "inactive" | "wrong_password") si falla
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None, "not_found"

    if not user.is_active:
        return None, "inactive"

    if not verify_password(password, user.password_hash):
        return None, "wrong_password"

    return user, None
