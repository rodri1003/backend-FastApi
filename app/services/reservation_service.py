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
from app.services import notification_service as notif_svc
from app.services.system_settings_service import get_tax_iva, get_tax_tourism, get_setting, get_cancellation_policy

def calculate_grand_total(reservation, db=None) -> Decimal:
    """
    Calcula el grand total de una reservación incluyendo habitación, extras e incidentales.
    
    Triple vía financiera:
    - total_cost: habitación (ya incluye IVA + turismo)
    - extras_total + IVA: amenidades extras del catálogo
    - incidentals_total + IVA (cuando aplica por cargo): cargos incidentales ad-hoc
    
    Si se pasa `db`, lee la tasa de IVA desde configuración; si no, usa 0.13.
    """
    if db:
        iva_rate = Decimal(str(get_tax_iva(db)))
    else:
        iva_rate = Decimal('0.13')
    
    extras_base = Decimal(str(reservation.extras_total or 0))
    extras_iva = extras_base * iva_rate
    
    # Incidentales: calcular IVA solo para los que aplican y no están condonados
    incidentals_base = Decimal(str(reservation.incidentals_total or 0))
    incidentals_tax = Decimal('0.0')
    if hasattr(reservation, 'incidental_charges'):
        for ch in reservation.incidental_charges:
            if ch.payment_status != "waived" and ch.apply_tax:
                incidentals_tax += Decimal(str(ch.total_amount)) * iva_rate
    else:
        # Fallback: aplicar IVA a todo el incidentals_total
        incidentals_tax = incidentals_base * iva_rate
    
    return (Decimal(str(reservation.total_cost)) 
            + extras_base + extras_iva 
            + incidentals_base + incidentals_tax)


def calculate_price(db: Session, room: Room, check_in: date, check_out: date) -> dict:
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
    
    tax_iva_rate = get_tax_iva(db)
    tax_tourism_rate = get_tax_tourism(db)
    tax_iva = subtotal * Decimal(str(tax_iva_rate))
    tax_tourism = subtotal * Decimal(str(tax_tourism_rate))
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

    # Validación de anticipación mínima
    min_advance_str = get_setting(db, "min_advance_booking_days", "0")
    try:
        min_advance = int(min_advance_str)
    except ValueError:
        min_advance = 0
        
    if min_advance > 0:
        min_date = get_el_salvador_today() + timedelta(days=min_advance)
        if data.check_in < min_date:
            raise HTTPException(
                status_code=400,
                detail=f"Debe reservar con al menos {min_advance} días de anticipación. La fecha mínima permitida es {min_date.strftime('%d/%m/%Y')}"
            )

    # Validación de estancia máxima
    max_stay_str = get_setting(db, "max_stay_nights", "30")
    try:
        max_stay = int(max_stay_str)
    except ValueError:
        max_stay = 30
        
    nights = (data.check_out - data.check_in).days
    if nights > max_stay:
        raise HTTPException(status_code=400, detail=f"La estancia máxima permitida es de {max_stay} noches")

    room = db.query(Room).options(selectinload(Room.season_prices)).filter(Room.id == data.room_id).first()
    if not room or not room.is_active:
        raise HTTPException(status_code=404, detail="Habitación no encontrada o inactiva")

    if data.guests > room.capacity:
        raise HTTPException(status_code=400, detail=f"La capacidad máxima es de {room.capacity} personas")

    validate_reservation_overlap(db, data.room_id, data.check_in, data.check_out)

    price_data = calculate_price(db, room, data.check_in, data.check_out)

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

    # Dispatch notificaciones
    try:
        notif_svc.notify_reservation_created(db, reservation)
    except Exception:
        pass  # No romper el flujo si falla la notificación

    return reservation

def update_reservation(db: Session, reservation: Reservation, data: AdminReservationUpdate) -> Reservation:
    new_check_in = data.check_in or reservation.check_in
    new_check_out = data.check_out or reservation.check_out
    new_room_id = data.room_id or reservation.room_id
    
    if new_check_in >= new_check_out:
        raise HTTPException(status_code=400, detail="Check-out must be after check-in")

    if data.check_in and data.check_in != reservation.check_in and data.check_in < get_el_salvador_today():
        raise HTTPException(status_code=400, detail="No puedes mover el check-in a una fecha pasada")

    # Validación de anticipación mínima en actualización
    min_advance_str = get_setting(db, "min_advance_booking_days", "0")
    try:
        min_advance = int(min_advance_str)
    except ValueError:
        min_advance = 0
        
    if min_advance > 0 and data.check_in and data.check_in != reservation.check_in:
        min_date = get_el_salvador_today() + timedelta(days=min_advance)
        if data.check_in < min_date:
            raise HTTPException(
                status_code=400,
                detail=f"Debe reservar con al menos {min_advance} días de anticipación. La fecha mínima permitida es {min_date.strftime('%d/%m/%Y')}"
            )

    # Validación de estancia máxima en actualización
    max_stay_str = get_setting(db, "max_stay_nights", "30")
    try:
        max_stay = int(max_stay_str)
    except ValueError:
        max_stay = 30
        
    nights = (new_check_out - new_check_in).days
    if nights > max_stay:
        raise HTTPException(status_code=400, detail=f"La estancia máxima permitida es de {max_stay} noches")

    # If dates OR room changed, check overlap and recalculate cost
    if data.check_in or data.check_out or data.room_id:
        validate_reservation_overlap(db, new_room_id, new_check_in, new_check_out, exclude_res_id=reservation.id)
            
        # We need the full room with season_prices for calculation
        room_full = db.query(Room).options(selectinload(Room.season_prices)).filter(Room.id == new_room_id).first()
        if not room_full:
            raise HTTPException(status_code=404, detail="Nueva habitación no encontrada")
            
        price_data = calculate_price(db, room_full, new_check_in, new_check_out)
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

    # Detectar si el status cambió a confirmed para notificar
    old_status = reservation.status

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

    # Dispatch notificación si se confirmó
    if old_status != "confirmed" and reservation.status == "confirmed":
        try:
            notif_svc.notify_reservation_confirmed(db, reservation)
        except Exception:
            pass

    return reservation

def cancel_reservation(db: Session, reservation: Reservation, background_tasks: BackgroundTasks = None):
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="Ya está cancelada")

    from decimal import Decimal

    total_paid = sum(p.amount for p in reservation.payments if p.status == "completed")
    
    # Solo aplicamos penalidades si el usuario ya había pagado algo
    if total_paid > 0:
        policy = get_cancellation_policy(db)
        days_until_checkin = (reservation.check_in - get_el_salvador_today()).days
        
        penalty_factor = Decimal("0.0")
        if days_until_checkin <= 0:
            penalty_factor = Decimal(str(policy["same_day_penalty"] / 100.0))
        elif days_until_checkin <= policy["short_notice_days"]:
            penalty_factor = Decimal(str(policy["short_notice_penalty"] / 100.0))
            
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

    # Dispatch notificación de cancelación
    try:
        notif_svc.notify_reservation_cancelled(db, reservation, cancelled_by="user")
    except Exception:
        pass

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
                timeout_str = get_setting(db, "pending_reservation_timeout_hours", "24")
                try:
                    timeout_hours = int(timeout_str)
                except ValueError:
                    timeout_hours = 24
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

