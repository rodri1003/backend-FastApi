from datetime import date
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload
from decimal import Decimal

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.room import Room
from app.models.reservation import Reservation
from app.schemas.reservation import ReservationCreate, ReservationRead, ReservationUpdate, AdminReservationCreate, AdminReservationUpdate
from app.services.reservation_service import (
    calculate_price, 
    create_admin_reservation, 
    update_reservation as service_update_reservation,
    cancel_reservation as service_cancel_reservation
)

router = APIRouter(prefix="/reservations", tags=["Reservations"])

@router.post("/", response_model=ReservationRead, status_code=status.HTTP_201_CREATED)
def create_reservation(
    data: ReservationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Convert ReservationCreate (user) to AdminReservationCreate (service expects this shape)
    admin_data = AdminReservationCreate(
        user_id=current_user.id,
        room_id=data.room_id,
        check_in=data.check_in,
        check_out=data.check_out,
        guests=data.guests
    )
    return create_admin_reservation(db, admin_data)

@router.get("/my", response_model=List[ReservationRead])
def get_my_reservations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Reservation).options(
        selectinload(Reservation.room)
    ).filter(
        Reservation.user_id == current_user.id, 
        Reservation.is_deleted == False
    ).order_by(Reservation.created_at.desc()).all()

@router.get("/{res_id}", response_model=ReservationRead)
def get_reservation(
    res_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reservation = db.query(Reservation).options(
        selectinload(Reservation.room)
    ).filter(Reservation.id == res_id, Reservation.is_deleted == False).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    roles = [r.name for r in current_user.roles]
    if reservation.user_id != current_user.id and "admin" not in roles and "manager" not in roles:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación")

    return reservation

@router.put("/{res_id}", response_model=ReservationRead)
def update_reservation(
    res_id: int,
    data: ReservationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reservation = db.query(Reservation).options(selectinload(Reservation.room)).filter(Reservation.id == res_id, Reservation.is_deleted == False).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    roles = [r.name for r in current_user.roles]
    if reservation.user_id != current_user.id and "admin" not in roles and "manager" not in roles:
        raise HTTPException(status_code=403, detail="No autorizado")

    # Convert ReservationUpdate to AdminReservationUpdate
    admin_update_data = AdminReservationUpdate(**data.model_dump())
    return service_update_reservation(db, reservation, admin_update_data)

@router.delete("/{res_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_reservation(
    res_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reservation = db.query(Reservation).filter(Reservation.id == res_id, Reservation.is_deleted == False).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    roles = [r.name for r in current_user.roles]
    if reservation.user_id != current_user.id and "admin" not in roles and "manager" not in roles:
        raise HTTPException(status_code=403, detail="No autorizado")

    service_cancel_reservation(db, reservation)
    return
