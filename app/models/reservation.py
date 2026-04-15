import uuid
from sqlalchemy import Column, Integer, String, Numeric, Date, ForeignKey, func, DateTime, Boolean
from sqlalchemy.orm import relationship

from app.db.session import Base

class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    unique_id = Column(String(50), nullable=False, unique=True, index=True, default=lambda: str(uuid.uuid4())[:12].upper())
    user_id = Column(Integer, ForeignKey("users.id", ondelete="NO ACTION"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="NO ACTION"), nullable=False)
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    guests = Column(Integer, nullable=False)
    total_cost = Column(Numeric(10, 2), nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # pending, confirmed, cancelled
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="reservations")
    room = relationship("Room", backref="reservations")
    payments = relationship("Payment", back_populates="reservation", cascade="all, delete-orphan")
