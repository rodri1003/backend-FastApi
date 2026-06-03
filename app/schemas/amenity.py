from pydantic import BaseModel

class AmenityCategoryCreate(BaseModel):
    name: str

class AmenityCategoryUpdate(BaseModel):
    name: str

class AmenityCategoryRead(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class AmenityCreate(BaseModel):
    name: str
    icon: str | None = None
    category_id: int | None = None

class AmenityUpdate(BaseModel):
    name: str | None = None
    icon: str | None = None
    category_id: int | None = None

class AmenityRead(BaseModel):
    id: int
    name: str
    icon: str | None = None
    category: AmenityCategoryRead | None = None

    class Config:
        from_attributes = True
