from app.core.ssl_patch import apply_ssl_patch
apply_ssl_patch()

# Patch urllib3 SSL verification for local environment (helps Cloudinary)
try:
    import ssl
    import urllib3
    import urllib3.util.ssl_
    import urllib3.connection
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # 1. Patch create_urllib3_context
    original_create_urllib3_context = urllib3.util.ssl_.create_urllib3_context
    def patched_create_urllib3_context(*args, **kwargs):
        kwargs['cert_reqs'] = ssl.CERT_NONE
        return original_create_urllib3_context(*args, **kwargs)
    urllib3.util.ssl_.create_urllib3_context = patched_create_urllib3_context
    urllib3.util.create_urllib3_context = patched_create_urllib3_context

    # 2. Patch ssl_wrap_socket
    original_ssl_wrap_socket = urllib3.util.ssl_.ssl_wrap_socket
    def patched_ssl_wrap_socket(*args, **kwargs):
        kwargs['cert_reqs'] = ssl.CERT_NONE
        if 'ssl_context' in kwargs and kwargs['ssl_context'] is not None:
            try:
                kwargs['ssl_context'].check_hostname = False
                kwargs['ssl_context'].verify_mode = ssl.CERT_NONE
            except Exception:
                pass
        return original_ssl_wrap_socket(*args, **kwargs)
    urllib3.util.ssl_.ssl_wrap_socket = patched_ssl_wrap_socket

    # 3. Patch urllib3.connection.HTTPSConnection.connect
    original_connect = urllib3.connection.HTTPSConnection.connect
    def patched_connect(self, *args, **kwargs):
        if hasattr(self, 'ssl_context') and self.ssl_context is not None:
            try:
                self.ssl_context.check_hostname = False
                self.ssl_context.verify_mode = ssl.CERT_NONE
            except Exception:
                pass
        if hasattr(self, 'cert_reqs'):
            self.cert_reqs = ssl.CERT_NONE
        return original_connect(self, *args, **kwargs)
    urllib3.connection.HTTPSConnection.connect = patched_connect
except Exception as e:
    pass

import cloudinary
import cloudinary.uploader
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from app.models.room import Room, RoomImage, SeasonPrice, RoomBasePriceHistory
from app.models.room_type import RoomType
from app.models.amenity import Amenity
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
        
    room_data = data.model_dump(exclude={"season_prices", "images", "type", "amenities"})
    room = Room(**room_data, room_type_id=room_type.id)
    
    for sp_data in data.season_prices:
        room.season_prices.append(SeasonPrice(**sp_data.model_dump(), snapshot_base_price=room.base_price))
        
    for idx, img_url in enumerate(data.images):
        room.images.append(RoomImage(url=img_url, sort_order=idx))
    
    # Auto-asignar portada si no se especificó una
    if not room.cover_image_url and data.images:
        room.cover_image_url = data.images[0]

    # Asignar amenidades del catálogo maestro
    if data.amenities:
        amenity_objects = db.query(Amenity).filter(
            Amenity.id.in_(data.amenities),
            Amenity.is_deleted == False
        ).all()
        room.amenities = amenity_objects
        
    room.base_price_history.append(RoomBasePriceHistory(base_price=room.base_price))
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
    update_data = data.model_dump(exclude_unset=True, exclude={"season_prices", "images", "type", "amenities"})
    
    if data.type is not None:
        rt = db.query(RoomType).filter(RoomType.name == data.type, RoomType.is_deleted == False).first()
        if not rt:
            raise HTTPException(status_code=400, detail=f"El tipo '{data.type}' no existe o fue eliminado.")
        update_data["room_type_id"] = rt.id

    old_base_price = room.base_price

    for key, value in update_data.items():
        setattr(room, key, value)
        
    if room.base_price != old_base_price:
        db.add(RoomBasePriceHistory(room_id=room.id, base_price=room.base_price))
        
    if data.season_prices is not None:
        existing_sps = db.query(SeasonPrice).filter(SeasonPrice.room_id == room.id, SeasonPrice.is_archived == False).all()
        existing_sp_dict = {sp.id: sp for sp in existing_sps}
        
        incoming_ids = [sp.id for sp in data.season_prices if getattr(sp, "id", None) is not None]
        
        # 1. Archive removed ones
        for sp in existing_sps:
            if sp.id not in incoming_ids:
                sp.is_archived = True

        # 2. Process incoming ones
        for sp_data in data.season_prices:
            if getattr(sp_data, "id", None) is not None and sp_data.id in existing_sp_dict:
                existing_sp = existing_sp_dict[sp_data.id]
                # Modificado?
                if (existing_sp.start_date != sp_data.start_date or
                    existing_sp.end_date != sp_data.end_date or
                    existing_sp.price_multiplier != sp_data.price_multiplier):
                    
                    # Archivar viejo y crear nuevo con nuevo snapshot
                    existing_sp.is_archived = True
                    new_sp = SeasonPrice(
                        room_id=room.id,
                        start_date=sp_data.start_date,
                        end_date=sp_data.end_date,
                        price_multiplier=sp_data.price_multiplier,
                        description=sp_data.description,
                        snapshot_base_price=room.base_price
                    )
                    db.add(new_sp)
                else:
                    # Sólo actualizar descripción si es que cambió
                    existing_sp.description = sp_data.description
            else:
                # Nuevo
                new_sp = SeasonPrice(
                    room_id=room.id,
                    start_date=sp_data.start_date,
                    end_date=sp_data.end_date,
                    price_multiplier=sp_data.price_multiplier,
                    description=sp_data.description,
                    snapshot_base_price=room.base_price
                )
                db.add(new_sp)
            
    if data.images is not None:
        db.query(RoomImage).filter(RoomImage.room_id == room.id).delete()
        for idx, img_url in enumerate(data.images):
            new_img = RoomImage(url=img_url, room_id=room.id, sort_order=idx)
            db.add(new_img)
        
        # Si se actualizaron imágenes y no hay portada (o la que había se eliminó), auto-asignar la primera
        if not room.cover_image_url and data.images:
            room.cover_image_url = data.images[0]
        elif room.cover_image_url and room.cover_image_url not in data.images:
            # Si la portada actual ya no está en la lista de imágenes,
            # pero hay otras disponibles, tomar la primera.
            if data.images:
                room.cover_image_url = data.images[0]
            else:
                room.cover_image_url = None
    
    # Actualizar amenidades del catálogo maestro
    if data.amenities is not None:
        amenity_objects = db.query(Amenity).filter(
            Amenity.id.in_(data.amenities),
            Amenity.is_deleted == False
        ).all()
        room.amenities = amenity_objects
        
    try:
        db.commit()
        db.refresh(room)
        db.refresh(room, ['season_prices', 'amenities', 'images'])
        return room
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error actualizando la habitación")
