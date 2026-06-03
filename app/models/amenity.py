from sqlalchemy import Column, Integer, String, Boolean, Table, ForeignKey
from app.db.session import Base

# Many-to-many pivot table: rooms <-> amenities
room_amenity_link = Table(
    "room_amenities",
    Base.metadata,
    Column("room_id", Integer, ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
    Column("amenity_id", Integer, ForeignKey("amenities.id", ondelete="CASCADE"), primary_key=True),
)

class AmenityCategory(Base):
    __tablename__ = "amenity_categories"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

class Amenity(Base):
    __tablename__ = "amenities"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    icon = Column(String(50), nullable=True)        # Lucide icon name: "wifi", "tv", "sparkles"
    category_id = Column(Integer, ForeignKey("amenity_categories.id", ondelete="SET NULL"), nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)

    from sqlalchemy.orm import relationship
    category = relationship("AmenityCategory", lazy="joined")
