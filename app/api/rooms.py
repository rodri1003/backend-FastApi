from datetime import date, timedelta
from typing import List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import or_, and_

from app.permissions.deps import require_permission
from app.db.session import get_db
from app.models.room import Room, SeasonPrice, RoomImage, RoomBasePriceHistory
from app.models.room_type import RoomType
from app.models.reservation import Reservation
from app.schemas.room import RoomRead, RoomSearchResponse, RoomCreate, RoomUpdate, RoomPriceHistoryResponse

from app.services.reservation_service import calculate_price
from app.services.room_service import create_room as service_create_room, update_room as service_update_room

router = APIRouter(prefix="/rooms", tags=["Rooms"])

@router.get("/search", response_model=List[RoomSearchResponse])
def search_rooms(
    check_in: date = Query(..., description="Fecha de entrada"),
    check_out: date = Query(..., description="Fecha de salida"),
    guests: int = Query(1, description="Número de personas"),
    room_type: Optional[str] = Query(None, description="Tipo de habitación"),
    db: Session = Depends(get_db)
):
    if check_in >= check_out:
        raise HTTPException(status_code=400, detail="Check-out must be after check-in.")

    # 1. Traer todas las habitaciones activas que cumplan capacidad y tipo
    q = db.query(Room).options(
        selectinload(Room.amenities),
        selectinload(Room.images),
        selectinload(Room.season_prices)
    ).filter(Room.is_active == True, Room.is_deleted == False, Room.capacity >= guests)
    
    if room_type:
        q = q.join(RoomType).filter(RoomType.name == room_type)
        
    rooms = q.all()

    # 2. Buscar reservaciones que se crucen con las fechas buscadas
    overlapping_reservations = db.query(Reservation).filter(
        Reservation.status.in_(["pending", "confirmed"]),
        Reservation.check_in < check_out,
        Reservation.check_out > check_in,
        Reservation.is_deleted == False
    ).all()
    
    occupied_room_ids = {res.room_id for res in overlapping_reservations}

    results = []
    for room in rooms:
        if room.id in occupied_room_ids:
            continue
            
        price_data = calculate_price(room, check_in, check_out)
        results.append(
            RoomSearchResponse(
                room=room,
                subtotal=price_data["subtotal"],
                tax_iva=price_data["tax_iva"],
                tax_tourism=price_data["tax_tourism"],
                total_price=price_data["total"],
                is_available=True
            )
        )
        
    return results

@router.get("/public", response_model=List[RoomRead])
def get_public_rooms(db: Session = Depends(get_db)):
    rooms = db.query(Room).options(
        selectinload(Room.amenities),
        selectinload(Room.images),
        selectinload(Room.season_prices)
    ).filter(Room.is_active == True, Room.is_deleted == False).limit(6).all()
    
    for r in rooms:
        r.season_prices = [sp for sp in r.season_prices if not sp.is_archived]
    return rooms

@router.get("/types", response_model=List[str])
def get_public_room_types(db: Session = Depends(get_db)):
    # Obtener nombres de tipos de habitación registrados
    types = db.query(RoomType.name).filter(
        RoomType.is_deleted == False
    ).all()
    return [t[0] for t in types]

@router.get("/{room_id}", response_model=RoomRead)
def get_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).options(
        selectinload(Room.amenities),
        selectinload(Room.images),
        selectinload(Room.season_prices)
    ).filter(Room.id == room_id, Room.is_deleted == False).first()
    
    if not room:
        raise HTTPException(status_code=404, detail="Habitación no encontrada")
    
    # Filtrar activas si es necesario, o la lectura normal ya devuelve ambas.
    # Preferiblemente RoomRead puede devolver solo activas y esta de abajo todas:
    room.season_prices = [sp for sp in room.season_prices if not sp.is_archived]
    return room

from app.schemas.room import SeasonPriceRead
@router.get("/{room_id}/price-history", response_model=RoomPriceHistoryResponse, dependencies=[Depends(require_permission("rooms", "read"))])
def get_room_price_history(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id, Room.is_deleted == False).first()
    if not room:
        raise HTTPException(status_code=404, detail="Habitación no encontrada")
    
    sp_prices = db.query(SeasonPrice).filter(SeasonPrice.room_id == room_id).order_by(SeasonPrice.created_at.desc(), SeasonPrice.id.desc()).all()
    bp_history = db.query(RoomBasePriceHistory).filter(RoomBasePriceHistory.room_id == room_id).order_by(RoomBasePriceHistory.created_at.desc(), RoomBasePriceHistory.id.desc()).all()
    
    return RoomPriceHistoryResponse(
        season_prices=sp_prices,
        base_prices=bp_history
    )

@router.post("/", response_model=RoomRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("rooms", "create"))])
def create_room(data: RoomCreate, db: Session = Depends(get_db)):
    return service_create_room(db, data)

@router.put("/{room_id}", response_model=RoomRead, dependencies=[Depends(require_permission("rooms", "update"))])
def update_room(room_id: int, data: RoomUpdate, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Habitación no encontrada")
    return service_update_room(db, room, data)

@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("rooms", "delete"))])
def delete_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Habitación no encontrada")
    
    # Verificar si hay reservaciones ACTIVAS o PENDIENTES (no canceladas)
    active_reservations = db.query(Reservation).filter(
        Reservation.room_id == room_id,
        Reservation.status != "cancelled"
    ).first()
    
    if active_reservations:
        raise HTTPException(
            status_code=400, 
            detail="No se puede eliminar la habitación porque tiene reservaciones pendientes o confirmadas. Cancele las reservaciones primero."
        )
        
    room.is_deleted = True
    room.is_active = False # Also deactivate it
    db.commit()
    return

@router.get("/", response_model=List[RoomRead], dependencies=[Depends(require_permission("rooms", "read"))])
def get_all_rooms_admin(db: Session = Depends(get_db)):
    rooms = db.query(Room).options(
        selectinload(Room.amenities),
        selectinload(Room.images),
        selectinload(Room.season_prices)
    ).filter(Room.is_deleted == False).all()
    
    for r in rooms:
        r.season_prices = [sp for sp in r.season_prices if not sp.is_archived]
    return rooms
