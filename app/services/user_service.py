from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate


def create_user(db: Session, user_in: UserCreate) -> User:
    exists_username = db.query(User).filter(User.username == user_in.username).first()
    if exists_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username ya existe."
        )

    exists_email = db.query(User).filter(User.email == user_in.email).first()
    if exists_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email ya existe."
        )

    user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        is_active=True
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user
