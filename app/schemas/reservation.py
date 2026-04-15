from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from app.schemas.room import RoomRead
from app.schemas.user import UserProfileRead

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

class ReservationCreate(ReservationBase):
    pass

class ReservationUpdate(BaseModel):
    check_in: date | None = None
    check_out: date | None = None
    guests: int | None = None

class AdminReservationCreate(ReservationBase):
    user_id: int

class AdminReservationUpdate(BaseModel):
    user_id: int | None = None
    room_id: int | None = None
    check_in: date | None = None
    check_out: date | None = None
    guests: int | None = None
    status: str | None = None

class ResPaymentRead(BaseModel):
    id: int
    amount: Decimal
    method: str
    status: str
    receipt_type: str | None
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
    total_cost: Decimal
    status: str
    created_at: datetime
    updated_at: datetime
    
    room: RoomRead | None = None
    user: ResUserRead | None = None
    payments: list[ResPaymentRead] = []
    
    @computed_field
    def total_paid(self) -> Decimal:
        return sum((p.amount for p in self.payments if p.status == "completed"), Decimal("0.0"))

    @computed_field
    def balance(self) -> Decimal:
        return self.total_cost - self.total_paid
    
    model_config = ConfigDict(from_attributes=True)
