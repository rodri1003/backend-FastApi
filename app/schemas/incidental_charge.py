"""
Schemas Pydantic para el sistema de Cargos Incidentales.
"""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────
# Categorías de Cargos Incidentales
# ─────────────────────────────────────────────

class IncidentalChargeCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    icon: str | None = None


class IncidentalChargeCategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    icon: str | None = None
    is_active: bool | None = None


class IncidentalChargeCategoryRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    icon: str | None = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────
# Cargos Incidentales
# ─────────────────────────────────────────────

class IncidentalChargeCreate(BaseModel):
    category_id: int | None = None
    description: str = Field(..., min_length=3, max_length=500)
    amount: Decimal = Field(..., gt=0)
    quantity: int = Field(1, ge=1, le=100)
    apply_tax: bool = True
    notes: str | None = None


class IncidentalChargeUpdate(BaseModel):
    category_id: int | None = None
    description: str | None = Field(None, min_length=3, max_length=500)
    amount: Decimal | None = Field(None, gt=0)
    quantity: int | None = Field(None, ge=1, le=100)
    apply_tax: bool | None = None
    notes: str | None = None


class IncidentalChargeWaive(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


class IncidentalChargeStaffRead(BaseModel):
    """Info mínima del staff que registró el cargo."""
    id: int
    email: str

    model_config = ConfigDict(from_attributes=True)


class IncidentalChargeRead(BaseModel):
    id: int
    reservation_id: int
    category: IncidentalChargeCategoryRead | None = None
    description: str
    amount: Decimal
    quantity: int
    total_amount: Decimal
    apply_tax: bool
    payment_status: str     # 'pending' | 'paid' | 'waived'
    waived_reason: str | None = None
    evidence_url: str | None = None
    notes: str | None = None
    created_by_user_id: int
    created_by: IncidentalChargeStaffRead | None = None
    reservation_unique_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncidentalChargeSummary(BaseModel):
    payment_status: str
    apply_tax: bool
    total_amount: Decimal

    model_config = ConfigDict(from_attributes=True)
