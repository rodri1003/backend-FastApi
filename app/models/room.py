from sqlalchemy import Column, Integer, String, Text, Numeric, Boolean, Date, ForeignKey, func, DateTime
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.models.amenity import Amenity, room_amenity_link

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    number = Column(String(50), unique=True, index=True, nullable=False)
    room_type_id = Column(Integer, ForeignKey("room_types.id"), nullable=False)
    capacity = Column(Integer, nullable=False)
    base_price = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)
    cover_image_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    amenities = relationship("Amenity", secondary=room_amenity_link, lazy="joined")
    images = relationship("RoomImage", back_populates="room", cascade="all, delete-orphan", order_by="RoomImage.sort_order")
    season_prices = relationship("SeasonPrice", back_populates="room", cascade="all, delete-orphan")
    base_price_history = relationship("RoomBasePriceHistory", back_populates="room", cascade="all, delete-orphan")
    room_type = relationship("RoomType", lazy="joined")

    @property
    def type(self) -> str | None:
        """Proxy property to maintain backwards compatibility with the API string contract."""
        return self.room_type.name if self.room_type else None


class RoomImage(Base):
    __tablename__ = "room_images"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(500), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    room = relationship("Room", back_populates="images")


class SeasonPrice(Base):
    __tablename__ = "season_prices"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    price_multiplier = Column(Numeric(5, 2), nullable=False)
    description = Column(String(255), nullable=True)
    
    # Historic Pricing Auditing Fields
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    snapshot_base_price = Column(Numeric(10, 2), nullable=True)

    room = relationship("Room", back_populates="season_prices")

class RoomBasePriceHistory(Base):
    __tablename__ = "room_baseprice_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    base_price = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    room = relationship("Room", back_populates="base_price_history")
