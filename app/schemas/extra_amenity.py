"""
Schemas Pydantic para el sistema de Amenidades Extras con costo.
"""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────
# Categorías
# ─────────────────────────────────────────────

class ExtraAmenityCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None


class ExtraAmenityCategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None


class ExtraAmenityCategoryRead(BaseModel):
    id: int
    name: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────
# Catálogo de Extras
# ─────────────────────────────────────────────

class ExtraAmenityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: str | None = None
    icon: str | None = None           # Nombre ícono Lucide
    image_url: str | None = None      # URL Cloudinary (se sube desde el endpoint)
    price: Decimal = Field(..., gt=0)
    category_id: int | None = None
    is_active: bool = True


class ExtraAmenityUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    description: str | None = None
    icon: str | None = None
    image_url: str | None = None
    price: Decimal | None = Field(None, gt=0)
    category_id: int | None = None
    is_active: bool | None = None


class ExtraAmenityRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    icon: str | None = None
    image_url: str | None = None
    price: Decimal
    category: ExtraAmenityCategoryRead | None = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────
# Pivot: Reservación <-> Extras
# ─────────────────────────────────────────────

class ReservationExtraCreate(BaseModel):
    extra_amenity_id: int
    quantity: int = Field(1, ge=1, le=50)
    notes: str | None = None


class ReservationExtraUpdate(BaseModel):
    quantity: int = Field(1, ge=1, le=50)
    notes: str | None = None



class ReservationExtraRead(BaseModel):
    id: int
    extra_amenity_id: int
    extra_amenity: ExtraAmenityRead
    quantity: int
    unit_price: Decimal        # Snapshot al momento de contratar
    total_price: Decimal       # quantity * unit_price
    payment_status: str        # 'pending' | 'paid' (independiente de reservation.status)
    notes: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
