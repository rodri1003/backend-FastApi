from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from app.schemas.reservation import ReservationRead, ReservationSummary

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
    receipt_url: str | None
    receipt_data: dict | None
    created_at: datetime
    
    reservation: ReservationRead | None = None
    
    model_config = ConfigDict(from_attributes=True)


class PaymentListItem(BaseModel):
    """Pago para listado — usa ReservationSummary en vez de ReservationRead.
    Esto elimina los lazy-loads por registro en el módulo de Pagos.
    """
    id: int
    reservation_id: int
    amount: Decimal
    method: str
    status: str
    receipt_type: str | None = None
    receipt_url: str | None = None
    receipt_data: dict | None = None
    created_at: datetime
    
    reservation: ReservationSummary | None = None
    
    model_config = ConfigDict(from_attributes=True)


class PaginatedPayments(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PaymentListItem]
