"""
Modelos para el sistema de notificaciones.
- Notification: notificaciones individuales por usuario.
- NotificationSetting: configuración global del sistema de notificaciones.
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = Column(String(30), nullable=False, index=True)        # reservation, payment, system, promotion
    severity = Column(String(20), nullable=False, default="info") # info, success, warning, alert
    title = Column(String(200), nullable=False)
    message = Column(String(500), nullable=False)
    reference_type = Column(String(50), nullable=True)  # reservation, payment, room, user
    reference_id = Column(Integer, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text('GETUTCDATE()'),
    )

    user = relationship("User", backref="notifications", foreign_keys=[user_id])


class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(String(500), nullable=False, default="true")
    description = Column(String(255), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text('GETUTCDATE()'),
        onupdate=func.now(),
    )
