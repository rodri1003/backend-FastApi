"""
Modelo para la configuración general del sistema.
"""
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    func,
    text,
)

from app.db.session import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False, default="")

    category = Column(String(50), nullable=False, default="general")
    description = Column(String(255), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("GETUTCDATE()"),
        onupdate=func.now(),
    )
