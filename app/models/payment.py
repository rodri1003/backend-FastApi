from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, func, DateTime, JSON, text
from sqlalchemy.orm import relationship

from app.db.session import Base

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    method = Column(String(50), nullable=False)  # eg card, transfer, cash
    status = Column(String(50), nullable=False, default="pending")  # pending, completed, failed
    receipt_type = Column(String(50), nullable=True)  # fiscal_credit, final_consumer
    receipt_data = Column(JSON, nullable=True)  # stored JSON for the frontend to render
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('GETUTCDATE()'))

    reservation = relationship("Reservation", back_populates="payments")
