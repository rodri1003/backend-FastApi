from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session, selectinload
from fastapi import HTTPException
from app.models.room import Room
from app.models.reservation import Reservation
from app.schemas.reservation import AdminReservationCreate, AdminReservationUpdate
from app.utils.date_utils import get_el_salvador_today

def calculate_price(room: Room, check_in: date, check_out: date) -> Decimal:
    """Calcula el precio total aplicando los multiplicadores de temporada."""
    total = Decimal("0.0")
    current_date = check_in
    while current_date < check_out:
        multiplier = Decimal("1.0")
        for sp in room.season_prices:
            if not getattr(sp, "is_archived", False) and sp.start_date <= current_date <= sp.end_date:
                multiplier = sp.price_multiplier
                break
        total += room.base_price * multiplier
        current_date += timedelta(days=1)
    return total

def validate_reservation_overlap(db: Session, room_id: int, check_in: date, check_out: date, exclude_res_id: int = None):
    """Verifica si hay reservaciones existentes que se crucen con las fechas dadas."""
    query = db.query(Reservation).filter(
        Reservation.room_id == room_id,
        Reservation.is_deleted == False,
        Reservation.status.in_(["pending", "confirmed"]),
        Reservation.check_in < check_out,
        Reservation.check_out > check_in
    )
    if exclude_res_id:
        query = query.filter(Reservation.id != exclude_res_id)
    
    overlap = query.first()
    if overlap:
        raise HTTPException(status_code=409, detail="La habitación ya no está disponible en esas fechas")
    return True

def create_admin_reservation(db: Session, data: AdminReservationCreate):
    if data.check_in >= data.check_out:
        raise HTTPException(status_code=400, detail="El Check-out debe ser después del check-in")
        
    if data.check_in < get_el_salvador_today():
        raise HTTPException(status_code=400, detail="No se pueden crear reservaciones en el pasado")

    room = db.query(Room).options(selectinload(Room.season_prices)).filter(Room.id == data.room_id).first()
    if not room or not room.is_active:
        raise HTTPException(status_code=404, detail="Habitación no encontrada o inactiva")

    if data.guests > room.capacity:
        raise HTTPException(status_code=400, detail=f"La capacidad máxima es de {room.capacity} personas")

    validate_reservation_overlap(db, data.room_id, data.check_in, data.check_out)

    total_cost = calculate_price(room, data.check_in, data.check_out)

    reservation = Reservation(
        user_id=data.user_id,
        room_id=data.room_id,
        check_in=data.check_in,
        check_out=data.check_out,
        guests=data.guests,
        total_cost=total_cost,
        status="pending"
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return reservation

def update_reservation(db: Session, reservation: Reservation, data: AdminReservationUpdate) -> Reservation:
    new_check_in = data.check_in or reservation.check_in
    new_check_out = data.check_out or reservation.check_out
    new_room_id = data.room_id or reservation.room_id
    
    if new_check_in >= new_check_out:
        raise HTTPException(status_code=400, detail="Check-out must be after check-in")

    if data.check_in and data.check_in != reservation.check_in and data.check_in < get_el_salvador_today():
        raise HTTPException(status_code=400, detail="No puedes mover el check-in a una fecha pasada")

    # If dates OR room changed, check overlap and recalculate cost
    if data.check_in or data.check_out or data.room_id:
        validate_reservation_overlap(db, new_room_id, new_check_in, new_check_out, exclude_res_id=reservation.id)
            
        # We need the full room with season_prices for calculation
        room_full = db.query(Room).options(selectinload(Room.season_prices)).filter(Room.id == new_room_id).first()
        if not room_full:
            raise HTTPException(status_code=404, detail="Nueva habitación no encontrada")
            
        reservation.total_cost = calculate_price(room_full, new_check_in, new_check_out)

    if data.check_in: reservation.check_in = data.check_in
    if data.check_out: reservation.check_out = data.check_out
    if data.room_id: reservation.room_id = data.room_id
    
    if data.guests:
        # Check target capacity (new room if updated, otherwise current room)
        target_capacity = room_full.capacity if (data.check_in or data.check_out or data.room_id) and room_full else reservation.room.capacity
        if data.guests > target_capacity:
            raise HTTPException(status_code=400, detail=f"La capacidad máxima es de {target_capacity} personas")
        reservation.guests = data.guests
        
    if data.status: reservation.status = data.status

    # Auto-adjust status based on balance
    if reservation.status != "cancelled":
        from app.models.payment import Payment
        from sqlalchemy import func
        from decimal import Decimal
        
        # Calculate total paid correctly converting to Decimal to prevent float crashes in SQLite/SQL Server
        raw_total_paid = db.query(func.sum(Payment.amount)).filter(
            Payment.reservation_id == reservation.id, 
            Payment.status == "completed"
        ).scalar() or 0.0
        
        total_paid = Decimal(str(raw_total_paid))
        total_cost = Decimal(str(reservation.total_cost))

        # Enforce strict policy: Only keep as confirmed if fully paid
        if total_cost > total_paid:
            reservation.status = "pending"
        elif reservation.status == "pending" and total_cost <= total_paid:
            reservation.status = "confirmed"

    db.commit()
    db.refresh(reservation)
    return reservation

def cancel_reservation(db: Session, reservation: Reservation):
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="Ya está cancelada")

    reservation.status = "cancelled"
    # Business Logic: Penalización de cancelación (si falta < 2 días, cobramos un 20%)
    days_until_checkin = (reservation.check_in - get_el_salvador_today()).days
    if days_until_checkin <= 2 and reservation.status == "confirmed":
        # logic for penalty if any
        pass
        
    db.commit()
    return True
