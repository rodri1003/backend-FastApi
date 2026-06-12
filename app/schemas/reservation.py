from datetime import date, datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, computed_field, Field
from app.schemas.room import RoomRead, RoomSummary
from app.schemas.user import UserProfileRead, UserSummary
from app.schemas.extra_amenity import ReservationExtraRead
from app.schemas.incidental_charge import IncidentalChargeRead, IncidentalChargeSummary

# Necesitamos un UserRead simplificado para devolver en ReservationRead
class ResUserRead(BaseModel):
    id: int
    email: str
    profile: UserProfileRead | None = None

    model_config = ConfigDict(from_attributes=True)

class ReservationBase(BaseModel):
    room_id: int
    check_in: date
    check_out: date
    guests: int
    payment_method: str | None = None

class ReservationCreate(ReservationBase):
    pass

class ReservationUpdate(BaseModel):
    check_in: date | None = None
    check_out: date | None = None
    guests: int | None = None
    payment_method: str | None = None

class AdminReservationCreate(ReservationBase):
    user_id: int

class AdminReservationUpdate(BaseModel):
    user_id: int | None = None
    room_id: int | None = None
    check_in: date | None = None
    check_out: date | None = None
    guests: int | None = None
    status: str | None = None
    payment_method: str | None = None

class ResPaymentRead(BaseModel):
    id: int
    amount: Decimal
    method: str
    status: str
    receipt_type: str | None
    receipt_data: dict | None = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

from pydantic import computed_field

class ReservationRead(BaseModel):
    id: int
    unique_id: str
    user_id: int
    room_id: int
    check_in: date
    check_out: date
    guests: int
    
    subtotal: Decimal | None = None
    tax_iva: Decimal | None = None
    tax_tourism: Decimal | None = None
    total_cost: Decimal          # SOLO habitación
    extras_total: Decimal = Decimal('0')  # SOLO extras (independiente)
    incidentals_total: Decimal = Decimal('0')  # SOLO cargos incidentales ad-hoc
    
    status: str
    payment_method: str | None = None
    created_at: datetime
    updated_at: datetime
    
    room: RoomRead | None = None
    user: ResUserRead | None = None
    payments: list[ResPaymentRead] = []
    extras: list[ReservationExtraRead] = []
    incidental_charges: list[IncidentalChargeRead] = []
    
    @computed_field
    def total_paid(self) -> Decimal:
        return sum((p.amount for p in self.payments if p.status == "completed"), Decimal("0.0"))

    @computed_field
    def grand_total(self) -> Decimal:
        """Total incluyendo habitación, extras e incidentales con IVA."""
        extras_iva = self.extras_total * Decimal('0.13')
        # Calcular IVA de incidentales solo para los que aplican impuesto y no están condonados
        incidentals_tax = Decimal('0.0')
        for ch in self.incidental_charges:
            if ch.payment_status != "waived" and ch.apply_tax:
                incidentals_tax += ch.total_amount * Decimal('0.13')
        return (self.total_cost 
                + self.extras_total + extras_iva 
                + self.incidentals_total + incidentals_tax)

    @computed_field
    def balance(self) -> Decimal:
        """Balance pendiente incluyendo habitación, extras e incidentales con IVA."""
        return self.grand_total - self.total_paid

    @computed_field
    def extras_pending(self) -> Decimal:
        """Suma de extras pendientes con IVA (13%)."""
        pending_base = sum((ex.total_price for ex in self.extras if ex.payment_status == "pending"), Decimal("0.0"))
        return pending_base * Decimal('1.13')

    @computed_field
    def incidentals_pending(self) -> Decimal:
        """Suma de cargos incidentales pendientes (con IVA cuando aplica)."""
        pending = Decimal("0.0")
        for ch in self.incidental_charges:
            if ch.payment_status == "pending":
                tax = ch.total_amount * Decimal('0.13') if ch.apply_tax else Decimal('0.0')
                pending += ch.total_amount + tax
        return pending
    
    model_config = ConfigDict(from_attributes=True)


class ReservationSummary(BaseModel):
    """Reservación mínima para embeber en listado de pagos."""
    id: int
    unique_id: str
    check_in: date
    check_out: date
    status: str
    user_id: int
    room_id: int
    subtotal: Decimal | None = None
    tax_iva: Decimal | None = None
    tax_tourism: Decimal | None = None
    total_cost: Decimal
    extras_total: Decimal = Decimal('0')
    incidentals_total: Decimal = Decimal('0')
    user: UserSummary | None = None
    room: RoomSummary | None = None
    incidental_charges: list[IncidentalChargeSummary] = []

    model_config = ConfigDict(from_attributes=True)


class ReservationListItem(BaseModel):
    """Reservación para el listado de admin/reservaciones (eager loaded)."""
    id: int
    unique_id: str
    user_id: int
    room_id: int
    check_in: date
    check_out: date
    guests: int
    
    subtotal: Decimal | None = None
    tax_iva: Decimal | None = None
    tax_tourism: Decimal | None = None
    total_cost: Decimal
    extras_total: Decimal = Decimal('0')
    incidentals_total: Decimal = Decimal('0')
    
    status: str
    payment_method: str | None = None
    created_at: datetime
    updated_at: datetime
    
    room: RoomSummary | None = None
    user: UserSummary | None = None

    payments: list[Any] = Field(default=[], exclude=True)
    extras: list[Any] = Field(default=[], exclude=True)
    incidental_charges: list[Any] = Field(default=[], exclude=True)

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    def total_paid(self) -> Decimal:
        return sum((p.amount for p in self.payments if p.status == "completed"), Decimal("0.0"))

    @computed_field
    def grand_total(self) -> Decimal:
        extras_iva = self.extras_total * Decimal('0.13')
        incidentals_tax = Decimal('0.0')
        for ch in self.incidental_charges:
            if ch.payment_status != "waived" and ch.apply_tax:
                incidentals_tax += ch.total_amount * Decimal('0.13')
        return (self.total_cost 
                + self.extras_total + extras_iva 
                + self.incidentals_total + incidentals_tax)

    @computed_field
    def balance(self) -> Decimal:
        return self.grand_total - self.total_paid

    @computed_field
    def extras_pending(self) -> Decimal:
        pending_base = sum((ex.total_price for ex in self.extras if ex.payment_status == "pending"), Decimal("0.0"))
        return pending_base * Decimal('1.13')

    @computed_field
    def incidentals_pending(self) -> Decimal:
        pending = Decimal("0.0")
        for ch in self.incidental_charges:
            if ch.payment_status == "pending":
                tax = ch.total_amount * Decimal('0.13') if ch.apply_tax else Decimal('0.0')
                pending += ch.total_amount + tax
        return pending
