from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field

class RoomTypeBase(BaseModel):
    name: str
    description: str | None = None

class RoomTypeCreate(RoomTypeBase):
    pass

class RoomTypeRead(RoomTypeBase):
    id: int

    class Config:
        from_attributes = True

class RoomAmenityRead(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class RoomImageRead(BaseModel):
    id: int
    url: str

    class Config:
        from_attributes = True

class SeasonPriceBase(BaseModel):
    start_date: date
    end_date: date
    price_multiplier: Decimal
    description: str | None = None

class SeasonPriceCreate(SeasonPriceBase):
    pass

class SeasonPriceUpdate(SeasonPriceBase):
    id: int | None = None

class SeasonPriceRead(SeasonPriceBase):
    id: int
    created_at: datetime | str | None = None
    is_archived: bool = False
    snapshot_base_price: Decimal | None = None

    class Config:
        from_attributes = True

class RoomBasePriceHistoryRead(BaseModel):
    id: int
    room_id: int
    base_price: Decimal
    created_at: datetime | str | None = None

    class Config:
        from_attributes = True

class RoomPriceHistoryResponse(BaseModel):
    season_prices: list[SeasonPriceRead] = []
    base_prices: list[RoomBasePriceHistoryRead] = []

class RoomBase(BaseModel):
    number: str
    type: str
    capacity: int
    base_price: Decimal
    description: str | None = None
    cover_image_url: str | None = None
    is_active: bool = True

class RoomCreate(RoomBase):
    season_prices: list[SeasonPriceCreate] = []
    images: list[str] = []

class RoomUpdate(BaseModel):
    number: str | None = None
    type: str | None = None
    capacity: int | None = None
    base_price: Decimal | None = None
    description: str | None = None
    cover_image_url: str | None = None
    is_active: bool | None = None
    season_prices: list[SeasonPriceUpdate] | None = None
    images: list[str] | None = None

class RoomRead(RoomBase):
    id: int
    number: str
    type: str
    capacity: int
    base_price: Decimal
    description: str | None = None
    is_active: bool
    amenities: list[RoomAmenityRead] = []
    images: list[RoomImageRead] = []
    season_prices: list[SeasonPriceRead] = []

    class Config:
        from_attributes = True

class RoomSearchResponse(BaseModel):
    room: RoomRead
    total_price: Decimal | None = None
    is_available: bool = True
