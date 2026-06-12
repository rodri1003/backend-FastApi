"""
Modelos para el sistema de Amenidades Extras con costo.

Arquitectura de doble vía financiera:
- Reservación.total_cost  → SOLO habitación (nunca se modifica por extras)
- Reservación.extras_total → SOLO extras (calculado dinámicamente)
- Cada ReservationExtraAmenity tiene su propio payment_status independiente
"""
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Boolean,
    ForeignKey, func, DateTime, text
)
from sqlalchemy.orm import relationship

from app.db.session import Base


class ExtraAmenityCategory(Base):
    """Categorías para organizar las amenidades extras (ej: Gastronomía, Bienestar)."""
    __tablename__ = "extra_amenity_categories"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)

    extras = relationship("ExtraAmenity", back_populates="category")


class ExtraAmenity(Base):
    """Catálogo maestro de amenidades extras con costo."""
    __tablename__ = "extra_amenities"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)          # Nombre del ícono Lucide
    image_url = Column(String(500), nullable=True)    # URL Cloudinary
    price = Column(Numeric(10, 2), nullable=False)    # Precio unitario
    category_id = Column(
        Integer, ForeignKey("extra_amenity_categories.id", ondelete="SET NULL"),
        nullable=True
    )
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=text('GETUTCDATE()')
    )

    category = relationship("ExtraAmenityCategory", back_populates="extras", lazy="joined")
    reservation_extras = relationship("ReservationExtraAmenity", back_populates="extra_amenity")


class ReservationExtraAmenity(Base):
    """
    Tabla pivot: reservaciones <-> extras.

    Diseño clave:
    - unit_price: Snapshot del precio al momento de contratar (inmutable).
    - payment_status: INDEPENDIENTE del status de la reservación.
      El status de reserva NUNCA cambia por saldo de extras.
    """
    __tablename__ = "reservation_extra_amenities"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    reservation_id = Column(
        Integer, ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    extra_amenity_id = Column(
        Integer, ForeignKey("extra_amenities.id", ondelete="NO ACTION"),
        nullable=False
    )
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(10, 2), nullable=False)   # Snapshot del precio
    total_price = Column(Numeric(10, 2), nullable=False)  # quantity * unit_price

    # Estados: 'pending' | 'paid'
    # IMPORTANTE: Independiente de reservation.status
    payment_status = Column(String(20), nullable=False, default="pending")

    notes = Column(String(500), nullable=True)  # Notas del staff (ej: "Alergia a nueces")
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=text('GETUTCDATE()')
    )

    reservation = relationship("Reservation", back_populates="extras")
    extra_amenity = relationship("ExtraAmenity", back_populates="reservation_extras", lazy="joined")
