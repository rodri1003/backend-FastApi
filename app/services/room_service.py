import cloudinary
import cloudinary.uploader
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from app.models.room import Room, RoomImage, SeasonPrice
from app.models.room_type import RoomType
from app.schemas.room import RoomCreate, RoomUpdate

def upload_image_to_cloudinary(file: UploadFile) -> str:
    try:
        result = cloudinary.uploader.upload(file.file)
        return result.get("secure_url")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir imagen a Cloudinary: {str(e)}")

def create_room(db: Session, data: RoomCreate) -> Room:
    room_type = db.query(RoomType).filter(RoomType.name == data.type, RoomType.is_deleted == False).first()
    if not room_type:
        raise HTTPException(status_code=400, detail=f"El tipo de habitación '{data.type}' no existe o está desactivado.")
        
    room_data = data.model_dump(exclude={"season_prices", "images", "type"})
    room = Room(**room_data, room_type_id=room_type.id)
    
    for sp_data in data.season_prices:
        room.season_prices.append(SeasonPrice(**sp_data.model_dump()))
        
    for img_url in data.images:
        room.images.append(RoomImage(url=img_url))
        
    db.add(room)
    try:
        db.commit()
        db.refresh(room)
        # Refrescar relaciones
        db.refresh(room, ['season_prices', 'amenities', 'images'])
        return room
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="El número de habitación ya existe o error en datos")

def update_room(db: Session, room: Room, data: RoomUpdate) -> Room:
    update_data = data.model_dump(exclude_unset=True, exclude={"season_prices", "images", "type"})
    
    if data.type is not None:
        rt = db.query(RoomType).filter(RoomType.name == data.type, RoomType.is_deleted == False).first()
        if not rt:
            raise HTTPException(status_code=400, detail=f"El tipo '{data.type}' no existe o fue eliminado.")
        update_data["room_type_id"] = rt.id

    for key, value in update_data.items():
        setattr(room, key, value)
        
    if data.season_prices is not None:
        db.query(SeasonPrice).filter(SeasonPrice.room_id == room.id).delete()
        for sp_data in data.season_prices:
            new_sp = SeasonPrice(**sp_data.model_dump())
            new_sp.room_id = room.id
            db.add(new_sp)
            
    if data.images is not None:
        db.query(RoomImage).filter(RoomImage.room_id == room.id).delete()
        for img_url in data.images:
            new_img = RoomImage(url=img_url, room_id=room.id)
            db.add(new_img)
        
    try:
        db.commit()
        db.refresh(room)
        db.refresh(room, ['season_prices', 'amenities', 'images'])
        return room
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error actualizando la habitación")
