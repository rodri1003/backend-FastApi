from datetime import date
import re
from pydantic import BaseModel, EmailStr, Field, field_validator


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
    
    country: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    municipality: str | None = Field(default=None, max_length=100)
    address_complement: str | None = Field(default=None, max_length=255)
    
    person_type: str | None = Field(default=None, max_length=20)
    document_type: str | None = Field(default=None, max_length=50)
    document_number: str | None = Field(default=None, max_length=50)
    nrc: str | None = Field(default=None, max_length=50)
    nit: str | None = Field(default=None, max_length=20)
    economic_activity: str | None = Field(default=None, max_length=255)
    taxpayer_type: str | None = Field(default=None, max_length=50)


class UserProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    avatar_url: str | None = Field(default=None, max_length=255)
    date_of_birth: date | None = None
    country: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    municipality: str | None = Field(default=None, max_length=100)
    address_complement: str | None = Field(default=None, max_length=255)
    person_type: str | None = Field(default=None, max_length=20)
    document_type: str | None = Field(default=None, max_length=50)
    document_number: str | None = Field(default=None, max_length=50)
    nrc: str | None = Field(default=None, max_length=50)
    nit: str | None = Field(default=None, max_length=20)
    economic_activity: str | None = Field(default=None, max_length=255)
    taxpayer_type: str | None = Field(default=None, max_length=50)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v:
            if not re.match(r"^\+?[1-9]\d{7,14}$", v.strip()):
                raise ValueError("El número de teléfono debe ser válido.")
        return v
        
    @field_validator("date_of_birth")
    @classmethod
    def validate_age_over_18(cls, v: date | None) -> date | None:
        if v is not None:
            from datetime import date as dt_date
            age = (dt_date.today() - v).days / 365.2425
            if age < 18:
                raise ValueError("El usuario debe ser mayor a 18 años.")
        return v


class UserProfileRead(UserProfileBase):
    id: int

    class Config:
        from_attributes = True


class UserBase(BaseModel):
    email: EmailStr




class UserCreate(UserBase, UserProfileBase):
    password: str = Field(..., min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("La contraseña debe tener al menos una letra mayúscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("La contraseña debe tener al menos una letra minúscula")
        if not re.search(r"\d", v):
            raise ValueError("La contraseña debe tener al menos un número")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("La contraseña debe tener al menos un carácter especial (!@#$%^&*...)")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v:
            if not re.match(r"^\+?[1-9]\d{7,14}$", v.strip()):
                raise ValueError("El número de teléfono debe ser válido.")
        return v
        
    @field_validator("date_of_birth")
    @classmethod
    def validate_age_over_18(cls, v: date | None) -> date | None:
        if v is not None:
            from datetime import date as dt_date
            age = (dt_date.today() - v).days / 365.2425
            if age < 18:
                raise ValueError("El usuario debe ser mayor a 18 años.")
        return v


class UserCreateAdmin(UserBase, UserProfileBase):
    """Para crear usuarios desde el admin (obligatorio asignar rol)."""
    password: str | None = Field(default=None, min_length=10, max_length=128)
    role_id: int = Field(..., gt=0)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Reutilizar lógica o copiar
        if not re.search(r"[A-Z]", v):
            raise ValueError("La contraseña debe tener al menos una letra mayúscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("La contraseña debe tener al menos una letra minúscula")
        if not re.search(r"\d", v):
            raise ValueError("La contraseña debe tener al menos un número")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("La contraseña debe tener al menos un carácter especial")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v:
            if not re.match(r"^\+?[1-9]\d{7,14}$", v.strip()):
                raise ValueError("El número de teléfono debe ser válido.")
        return v
        
    @field_validator("date_of_birth")
    @classmethod
    def validate_age_over_18(cls, v: date | None) -> date | None:
        if v is not None:
            from datetime import date as dt_date
            age = (dt_date.today() - v).days / 365.2425
            if age < 18:
                raise ValueError("El usuario debe ser mayor a 18 años.")
        return v


class UserUpdateAdmin(BaseModel):
    """Para editar usuario desde admin."""
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    role_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    phone: str | None = Field(default=None, max_length=50)
    date_of_birth: date | None = None
    country: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    municipality: str | None = Field(default=None, max_length=100)
    address_complement: str | None = Field(default=None, max_length=255)
    person_type: str | None = Field(default=None, max_length=20)
    document_type: str | None = Field(default=None, max_length=50)
    document_number: str | None = Field(default=None, max_length=50)
    nrc: str | None = Field(default=None, max_length=50)
    nit: str | None = Field(default=None, max_length=20)
    economic_activity: str | None = Field(default=None, max_length=255)
    taxpayer_type: str | None = Field(default=None, max_length=50)
    
    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v:
            if not re.match(r"^\+?[1-9]\d{7,14}$", v.strip()):
                raise ValueError("El número de teléfono debe ser válido.")
        return v
        
    @field_validator("date_of_birth")
    @classmethod
    def validate_age_over_18(cls, v: date | None) -> date | None:
        if v is not None:
            from datetime import date as dt_date
            age = (dt_date.today() - v).days / 365.2425
            if age < 18:
                raise ValueError("El usuario debe ser mayor a 18 años.")
        return v


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
