"""
Schemas Pydantic para el sistema de notificaciones.
"""
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationRead(BaseModel):
    id: int
    user_id: int
    type: str
    severity: str
    title: str
    message: str
    reference_type: str | None = None
    reference_id: int | None = None
    is_read: bool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v

    model_config = ConfigDict(from_attributes=True)


class NotificationUnreadCount(BaseModel):
    count: int


class NotificationSettingRead(BaseModel):
    id: int
    key: str
    value: str
    description: str | None = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationSettingUpdate(BaseModel):
    value: str = Field(..., min_length=1, max_length=500)
