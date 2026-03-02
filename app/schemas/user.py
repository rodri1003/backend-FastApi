from datetime import date

from pydantic import BaseModel, EmailStr, Field


class RoleRead(BaseModel):
    id: int
    name: str
    description: str | None = None

    class Config:
        from_attributes = True


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


class UserRead(UserBase):
    id: int
    is_active: bool
    is_verified: bool
    roles: list[RoleRead] = []
    profile: UserProfileRead | None = None

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
