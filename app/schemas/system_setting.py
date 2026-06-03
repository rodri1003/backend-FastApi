"""
Schemas Pydantic para la configuración del sistema.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class SystemSettingRead(BaseModel):
    id: int
    key: str
    value: str
    category: str
    description: str | None = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SystemSettingUpdate(BaseModel):
    value: str = Field(min_length=0, max_length=500)


class SystemSettingBulkUpdate(BaseModel):
    settings: dict[str, str]  # { "key": "new_value", ... }
