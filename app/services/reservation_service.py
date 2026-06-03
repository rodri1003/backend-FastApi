from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session, selectinload
from fastapi import HTTPException
from app.models.room import Room
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.reservation import AdminReservationCreate, AdminReservationUpdate
from app.utils.date_utils import get_el_salvador_today
from app.core.config import settings
from fastapi import BackgroundTasks
from app.core.mail import send_reservation_cancelled_email, send_checkin_reminder_email

def calculate_price(room: Room, check_in: date, check_out: date) -> dict:
    """Calcula el precio total aplicando los multiplicadores de temporada e impuestos."""
    subtotal = Decimal("0.0")
    current_date = check_in
    while current_date < check_out:
        multiplier = Decimal("1.0")
        for sp in room.season_prices:
            if not getattr(sp, "is_archived", False) and sp.start_date <= current_date <= sp.end_date:
                multiplier = sp.price_multiplier
                break
        subtotal += room.base_price * multiplier
        current_date += timedelta(days=1)
    
    tax_iva = subtotal * Decimal(str(settings.TAX_IVA))
    tax_tourism = subtotal * Decimal(str(settings.TAX_TOURISM))
    total = subtotal + tax_iva + tax_tourism
    
    return {
        "subtotal": subtotal,
        "tax_iva": tax_iva,
        "tax_tourism": tax_tourism,
        "total": total
    }

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

    price_data = calculate_price(room, data.check_in, data.check_out)

    reservation = Reservation(
        user_id=data.user_id,
        room_id=data.room_id,
        check_in=data.check_in,
        check_out=data.check_out,
        guests=data.guests,
        subtotal=price_data["subtotal"],
        tax_iva=price_data["tax_iva"],
        tax_tourism=price_data["tax_tourism"],
        total_cost=price_data["total"],
        status="pending",
        payment_method=data.payment_method
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
            
        price_data = calculate_price(room_full, new_check_in, new_check_out)
        reservation.subtotal = price_data["subtotal"]
        reservation.tax_iva = price_data["tax_iva"]
        reservation.tax_tourism = price_data["tax_tourism"]
        reservation.total_cost = price_data["total"]

    if data.check_in: reservation.check_in = data.check_in
    if data.check_out: reservation.check_out = data.check_out
    if data.room_id: reservation.room_id = data.room_id
    if data.payment_method is not None: reservation.payment_method = data.payment_method
    
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

def cancel_reservation(db: Session, reservation: Reservation, background_tasks: BackgroundTasks = None):
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="Ya está cancelada")

    from decimal import Decimal

    total_paid = sum(p.amount for p in reservation.payments if p.status == "completed")
    
    # Solo aplicamos penalidades si el usuario ya había pagado algo
    if total_paid > 0:
        days_until_checkin = (reservation.check_in - get_el_salvador_today()).days
        
        penalty_factor = Decimal("0.0")
        if days_until_checkin <= 0:
            penalty_factor = Decimal("1.0") # 100% penalidad
        elif days_until_checkin <= 2:
            penalty_factor = Decimal("0.2") # 20% penalidad
            
        # Ajustamos los costos de la reservación a la penalidad
        reservation.subtotal = reservation.subtotal * penalty_factor if reservation.subtotal else Decimal("0.0")
        reservation.tax_iva = reservation.tax_iva * penalty_factor if reservation.tax_iva else Decimal("0.0")
        reservation.tax_tourism = reservation.tax_tourism * penalty_factor if reservation.tax_tourism else Decimal("0.0")
        reservation.total_cost = reservation.total_cost * penalty_factor
    else:
        # Si no había pagado nada, simplemente se anula el cobro
        reservation.subtotal = Decimal("0.0")
        reservation.tax_iva = Decimal("0.0")
        reservation.tax_tourism = Decimal("0.0")
        reservation.total_cost = Decimal("0.0")

    reservation.status = "cancelled"
    db.commit()

    # Enviar correo de cancelación
    if reservation.user and reservation.user.email and background_tasks:
        first_name = reservation.user.profile.first_name if reservation.user.profile else "Cliente"
        background_tasks.add_task(
            send_reservation_cancelled_email,
            email=reservation.user.email,
            first_name=first_name,
            reservation_id=reservation.unique_id
        )
        
    return True

from datetime import datetime, timezone
import asyncio
from app.db.session import SessionLocal

async def auto_cancel_expired_reservations():
    """
    Background task that periodically checks for pending reservations that have
    exceeded their payment timeout and cancels them.
    """
    while True:
        try:
            db = SessionLocal()
            now = get_el_salvador_today()
            # actually we need precise time for the timeouts (created_at is UTC datetime)
            current_utc = datetime.now(timezone.utc)
            
            pending_reservations = db.query(Reservation).options(
                selectinload(Reservation.user).selectinload(User.profile)
            ).filter(
                Reservation.status == "pending",
                Reservation.is_deleted == False
            ).all()

            for res in pending_reservations:
                # Utilizamos el tiempo de gracia general para reservas pendientes
                timeout_hours = settings.PENDING_RESERVATION_TIMEOUT_HOURS
                expiration_time = res.updated_at + timedelta(hours=timeout_hours)
                
                if current_utc > expiration_time:
                    print(f"[Auto-Cancel] Cancelando reservación {res.id} expirada en {expiration_time}")
                    res.status = "cancelled"
                    
                    # Notificar al cliente
                    if res.user and res.user.email:
                        first_name = res.user.profile.first_name if res.user.profile else "Cliente"
                        await send_reservation_cancelled_email(
                            email=res.user.email,
                            first_name=first_name,
                            reservation_id=res.unique_id,
                            reason="Tiempo de espera para pago agotado"
                        )
            
            db.commit()
            db.close()
            
        except Exception as e:
            print(f"[Scheduler Error]: {str(e)}")
            
        # Run every 5 minutes
        await asyncio.sleep(300)

async def auto_send_checkin_reminders():
    """
    Background task that sends a reminder email to guests 24 hours before their check-in.
    """
    while True:
        try:
            db = SessionLocal()
            today = get_el_salvador_today()
            tomorrow = today + timedelta(days=1)
            
            # Buscar reservas confirmadas que inician mañana y no han recibido recordatorio
            reminders_pending = db.query(Reservation).options(
                selectinload(Reservation.user).selectinload(User.profile),
                selectinload(Reservation.room)
            ).filter(
                Reservation.status == "confirmed",
                Reservation.is_deleted == False,
                Reservation.check_in == tomorrow,
                Reservation.reminder_sent == False
            ).all()

            for res in reminders_pending:
                if res.user and res.user.email:
                    first_name = res.user.profile.first_name if res.user.profile else "Cliente"
                    # print(f"[Reminder] Enviando recordatorio a {res.user.email} para reserva {res.unique_id}")
                    
                    # Como esto es un thread separado, no tenemos BackgroundTasks de FastAPI aquí,
                    # llamamos directamente a la función asíncrona.
                    await send_checkin_reminder_email(
                        email=res.user.email,
                        first_name=first_name,
                        reservation_id=res.unique_id,
                        check_in=res.check_in.strftime("%d/%m/%Y"),
                        room_name=f"Habitación {res.room.number} ({res.room.type})"
                    )
                    
                    res.reminder_sent = True
            
            db.commit()
            db.close()
            
        except Exception as e:
            print(f"[Reminder Scheduler Error]: {str(e)}")
            
        # Run every 4 hours
        await asyncio.sleep(14400)

