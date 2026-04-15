from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from app.schemas.reservation import ReservationRead

class PaymentBase(BaseModel):
    reservation_id: int
    amount: Decimal
    method: str
    receipt_type: str | None = None

class PaymentCreate(PaymentBase):
    pass

class PaymentRead(BaseModel):
    id: int
    reservation_id: int
    amount: Decimal
    method: str
    status: str
    receipt_type: str | None
    receipt_data: dict | None
    created_at: datetime
    
    reservation: ReservationRead | None = None
    
    model_config = ConfigDict(from_attributes=True)
