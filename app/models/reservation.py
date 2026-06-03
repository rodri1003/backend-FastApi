import uuid
from sqlalchemy import Column, Integer, String, Numeric, Date, ForeignKey, func, DateTime, Boolean, text
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
    
    subtotal = Column(Numeric(10, 2), nullable=True)
    tax_iva = Column(Numeric(10, 2), nullable=True)
    tax_tourism = Column(Numeric(10, 2), nullable=True)
    total_cost = Column(Numeric(10, 2), nullable=False)  # SOLO habitación, no incluye extras

    # Extras: independiente de total_cost para no afectar el estado de la reserva.
    # Ver: app/models/extra_amenity.py — ReservationExtraAmenity.payment_status
    extras_total = Column(Numeric(10, 2), nullable=False, default=0)

    # Cargos incidentales: ad-hoc, registrados por staff (independiente de extras y total_cost)
    # Ver: app/models/incidental_charge.py — IncidentalCharge.payment_status
    incidentals_total = Column(Numeric(10, 2), nullable=False, default=0)
    
    status = Column(String(50), nullable=False, default="pending")  # pending, verifying, confirmed, cancelled
    payment_method = Column(String(50), nullable=True)  # card, transfer, cash
    is_deleted = Column(Boolean, default=False, nullable=False)
    reminder_sent = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('GETUTCDATE()'))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text('GETUTCDATE()'), onupdate=func.now())

    user = relationship("User", backref="reservations")
    room = relationship("Room", backref="reservations")
    payments = relationship("Payment", back_populates="reservation", cascade="all, delete-orphan")
    extras = relationship("ReservationExtraAmenity", back_populates="reservation", cascade="all, delete-orphan")
    incidental_charges = relationship("IncidentalCharge", back_populates="reservation", cascade="all, delete-orphan")
