from sqlalchemy.orm import Session, selectinload
from fastapi import HTTPException, status

from app.core.security import hash_password, verify_password
from app.models.user import Role, User, UserProfile, UserRole
from app.schemas.user import UserCreate, UserCreateAdmin, UserUpdateAdmin, UserProfileUpdate


def create_user(db: Session, user_in: UserCreate) -> User:
    exists_email = db.query(User).filter(User.email == user_in.email).first()
    if exists_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email ya existe.",
        )

    if user_in.phone:
        exists_phone = db.query(UserProfile).filter(UserProfile.phone == user_in.phone).first()
        if exists_phone:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El número de teléfono ya está registrado por otro usuario.",
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
        country=user_in.country,
        department=user_in.department,
        municipality=user_in.municipality,
        address_complement=user_in.address_complement,
        person_type=user_in.person_type,
        business_name=user_in.business_name,
        nrc=user_in.nrc,
        document_type=user_in.document_type,
        document_number=user_in.document_number,
        nit=user_in.nit,
        economic_activity=user_in.economic_activity,
        taxpayer_type=user_in.taxpayer_type,
    )
    db.add(profile)

    # Rol por defecto "cliente" (si existe; el seed lo crea al arrancar)
    default_role = db.query(Role).filter(Role.name == "cliente").first()
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


def update_user_profile(db: Session, user_id: int, data: UserProfileUpdate) -> User:
    user = db.query(User).options(selectinload(User.profile)).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    
    if user.profile:
        update_data = data.model_dump(exclude_unset=True)
        if "first_name" in update_data:
            user.profile.first_name = update_data["first_name"]
        if "last_name" in update_data:
            user.profile.last_name = update_data["last_name"]
        if "phone" in update_data:
            phone_val = update_data["phone"]
            if phone_val:
                exists_phone = db.query(UserProfile).filter(UserProfile.phone == phone_val, UserProfile.user_id != user_id).first()
                if exists_phone:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El número de teléfono ya está registrado por otro usuario.")
            user.profile.phone = phone_val
        if "avatar_url" in update_data:
            user.profile.avatar_url = update_data["avatar_url"]
        if "date_of_birth" in update_data:
            user.profile.date_of_birth = update_data["date_of_birth"]
        if "country" in update_data:
            user.profile.country = update_data["country"]
        if "department" in update_data:
            user.profile.department = update_data["department"]
        if "municipality" in update_data:
            user.profile.municipality = update_data["municipality"]
        if "address_complement" in update_data:
            user.profile.address_complement = update_data["address_complement"]
        if "person_type" in update_data:
            user.profile.person_type = update_data["person_type"]
        if "business_name" in update_data:
            user.profile.business_name = update_data["business_name"]
        if "nrc" in update_data:
            user.profile.nrc = update_data["nrc"]
        if "document_type" in update_data:
            user.profile.document_type = update_data["document_type"]
        if "document_number" in update_data:
            user.profile.document_number = update_data["document_number"]
        if "nit" in update_data:
            user.profile.nit = update_data["nit"]
        if "economic_activity" in update_data:
            user.profile.economic_activity = update_data["economic_activity"]
        if "taxpayer_type" in update_data:
            user.profile.taxpayer_type = update_data["taxpayer_type"]
    db.commit()
    db.refresh(user)
    return user



def create_user_admin(db: Session, user_in: UserCreateAdmin) -> User:
    """Crea un usuario desde el panel admin, con rol asignado."""
    exists = db.query(User).filter(User.email == user_in.email).first()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya existe.",
        )

    if user_in.phone:
        exists_phone = db.query(UserProfile).filter(UserProfile.phone == user_in.phone).first()
        if exists_phone:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El número de teléfono ya está registrado por otro usuario.",
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
        country=user_in.country,
        department=user_in.department,
        municipality=user_in.municipality,
        address_complement=user_in.address_complement,
        person_type=user_in.person_type,
        business_name=user_in.business_name,
        nrc=user_in.nrc,
        document_type=user_in.document_type,
        document_number=user_in.document_number,
        nit=user_in.nit,
        economic_activity=user_in.economic_activity,
        taxpayer_type=user_in.taxpayer_type,
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
        update_data = data.model_dump(exclude_unset=True)
        if "first_name" in update_data and update_data["first_name"] is not None:
            user.profile.first_name = update_data["first_name"]
        if "last_name" in update_data and update_data["last_name"] is not None:
            user.profile.last_name = update_data["last_name"]
        if "phone" in update_data:
            phone_val = update_data["phone"]
            if phone_val:
                exists_phone = db.query(UserProfile).filter(UserProfile.phone == phone_val, UserProfile.user_id != user_id).first()
                if exists_phone:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El número de teléfono ya está registrado por otro usuario.")
            user.profile.phone = phone_val
        if "date_of_birth" in update_data:
            user.profile.date_of_birth = update_data["date_of_birth"]
        if "country" in update_data:
            user.profile.country = update_data["country"]
        if "department" in update_data:
            user.profile.department = update_data["department"]
        if "municipality" in update_data:
            user.profile.municipality = update_data["municipality"]
        if "address_complement" in update_data:
            user.profile.address_complement = update_data["address_complement"]
        if "person_type" in update_data:
            user.profile.person_type = update_data["person_type"]
        if "business_name" in update_data:
            user.profile.business_name = update_data["business_name"]
        if "nrc" in update_data:
            user.profile.nrc = update_data["nrc"]
        if "document_type" in update_data:
            user.profile.document_type = update_data["document_type"]
        if "document_number" in update_data:
            user.profile.document_number = update_data["document_number"]
        if "nit" in update_data:
            user.profile.nit = update_data["nit"]
        if "economic_activity" in update_data:
            user.profile.economic_activity = update_data["economic_activity"]
        if "taxpayer_type" in update_data:
            user.profile.taxpayer_type = update_data["taxpayer_type"]
    db.commit()
    db.refresh(user)
    return user
