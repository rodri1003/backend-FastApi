"""
Modelos para el sistema de Cargos Incidentales (ad-hoc).

Arquitectura de triple vía financiera:
- Reservación.total_cost       → SOLO habitación (nunca se modifica por incidentales)
- Reservación.extras_total     → SOLO extras de catálogo
- Reservación.incidentals_total → SOLO cargos incidentales ad-hoc

Cada IncidentalCharge tiene su propio payment_status independiente.
El status de la reservación NUNCA cambia por cargos incidentales.
"""
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Boolean,
    ForeignKey, func, DateTime, text
)
from sqlalchemy.orm import relationship

from app.db.session import Base


class IncidentalChargeCategory(Base):
    """Categorías predefinidas para clasificar cargos incidentales.
    Ej: 'Daños a Propiedad', 'Minibar', 'Servicios Adicionales', 'Multas', 'Otros'
    """
    __tablename__ = "incidental_charge_categories"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    icon = Column(String(50), nullable=True)          # Nombre del ícono Lucide
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    charges = relationship("IncidentalCharge", back_populates="category")


class IncidentalCharge(Base):
    """
    Cargo incidental individual vinculado a una reservación.

    Diseño clave:
    - amount: Monto definido manualmente por el staff (NO viene de catálogo).
    - payment_status: INDEPENDIENTE de reservation.status.
      'pending' | 'paid' | 'waived' (condonado/perdonado)
    - created_by_user_id: Staff que registró el cargo (trazabilidad).
    - apply_tax: Si se aplica IVA al cargo (configurable por cargo).
    """
    __tablename__ = "incidental_charges"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    reservation_id = Column(
        Integer, ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    category_id = Column(
        Integer, ForeignKey("incidental_charge_categories.id", ondelete="SET NULL"),
        nullable=True
    )

    description = Column(String(500), nullable=False)          # Descripción libre del cargo
    amount = Column(Numeric(10, 2), nullable=False)            # Monto unitario (sin IVA)
    quantity = Column(Integer, nullable=False, default=1)
    total_amount = Column(Numeric(10, 2), nullable=False)      # amount * quantity
    apply_tax = Column(Boolean, default=True, nullable=False)  # Si aplica IVA

    # Estados: 'pending' | 'paid' | 'waived'
    payment_status = Column(String(20), nullable=False, default="pending")
    waived_reason = Column(String(500), nullable=True)         # Motivo si fue condonado

    evidence_url = Column(String(500), nullable=True)          # Foto/evidencia (Cloudinary)
    notes = Column(String(1000), nullable=True)                # Notas internas del staff

    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="NO ACTION"),
        nullable=False
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=text('GETUTCDATE()')
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=text('GETUTCDATE()'),
        onupdate=func.now()
    )

    # Relationships
    reservation = relationship("Reservation", back_populates="incidental_charges")
    category = relationship("IncidentalChargeCategory", back_populates="charges", lazy="joined")
    created_by = relationship("User", foreign_keys=[created_by_user_id], lazy="joined")

    @property
    def reservation_unique_id(self) -> str | None:
        return self.reservation.unique_id if self.reservation else None
