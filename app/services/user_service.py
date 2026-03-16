from sqlalchemy.orm import Session, selectinload
from fastapi import HTTPException, status

from app.core.security import hash_password, verify_password
from app.models.user import Role, User, UserProfile, UserRole
from app.schemas.user import UserCreate, UserCreateAdmin, UserUpdateAdmin


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


def create_user_admin(db: Session, user_in: UserCreateAdmin) -> User:
    """Crea un usuario desde el panel admin, con rol asignado."""
    exists = db.query(User).filter(User.email == user_in.email).first()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya existe.",
        )

    role = db.query(Role).filter(Role.id == user_in.role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol no encontrado.",
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
    user.roles.append(role)
    db.commit()
    db.refresh(user)
    return user


def update_user_admin(
    db: Session, user_id: int, data: UserUpdateAdmin, *, current_user_id: int | None = None
) -> User:
    """Actualiza un usuario desde el panel admin."""
    user = (
        db.query(User)
        .options(
            selectinload(User.roles),
            selectinload(User.profile),
        )
        .filter(User.id == user_id)
        .first()
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")

    if current_user_id is not None and user_id == current_user_id and data.role_id is not None:
        current_role_id = user.roles[0].id if user.roles else None
        if data.role_id != current_role_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No puedes cambiar tu propio rol.",
            )

    if data.email is not None:
        other = db.query(User).filter(User.email == data.email, User.id != user_id).first()
        if other:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El email ya existe.")
        user.email = data.email

    if data.is_active is not None:
        user.is_active = data.is_active

    if data.role_id is not None:
        role = db.query(Role).filter(Role.id == data.role_id).first()
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rol no encontrado.")
        user.roles.clear()
        user.roles.append(role)

    if user.profile:
        if data.first_name is not None:
            user.profile.first_name = data.first_name
        if data.last_name is not None:
            user.profile.last_name = data.last_name

    db.commit()
    db.refresh(user)
    return user
