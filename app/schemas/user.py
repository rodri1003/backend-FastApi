from datetime import date

from pydantic import BaseModel, EmailStr, Field


class RoleRead(BaseModel):
    id: int
    name: str
    description: str | None = None

    class Config:
        from_attributes = True


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=255)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=255)


class UserProfileBase(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    avatar_url: str | None = Field(default=None, max_length=255)
    date_of_birth: date | None = None


class UserProfileRead(UserProfileBase):
    id: int

    class Config:
        from_attributes = True


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase, UserProfileBase):
    password: str = Field(..., min_length=8, max_length=128)


class UserCreateAdmin(UserBase, UserProfileBase):
    """Para crear usuarios desde el admin (obligatorio asignar rol)."""
    password: str = Field(..., min_length=8, max_length=128)
    role_id: int = Field(..., gt=0)


class UserUpdateAdmin(BaseModel):
    """Para editar usuario desde admin."""
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    role_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class UserRead(UserBase):
    id: int
    is_active: bool
    is_verified: bool
    roles: list[RoleRead] = []
    profile: UserProfileRead | None = None

    class Config:
        from_attributes = True


class UserMeRead(UserRead):
    """Usuario actual con permisos efectivos (resource:action) para el frontend."""
    permissions: list[str] = []


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
