"""
API administrativa: usuarios, roles, permisos (Casbin) y bitácora.
Acceso mediante permisos granulares (users:read, roles:create, etc.).
"""
import secrets
import string
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Query, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.mail import (
    send_welcome_email, 
    send_reservation_confirmed_email, 
    send_reservation_cancelled_email,
    send_payment_rejected_email,
    send_refund_processed_email,
    send_payment_receipt_email
)
from app.services.pdf_service import generate_receipt_pdf
from app.services.dte_json_service import generate_dte_json
from app.db.session import get_db
from app.models.user import User, Role, UserRole
from app.models.audit import AuditLog
from app.models.room import Room
from app.models.reservation import Reservation
from app.models.payment import Payment
from app.models.room_type import RoomType
from sqlalchemy import func, cast, Date, text
from app.schemas.user import UserRead, UserCreateAdmin, UserUpdateAdmin, RoleRead, RoleCreate, RoleUpdate, UserSummary
from app.schemas.reservation import ReservationRead, AdminReservationCreate, AdminReservationUpdate, ReservationListItem, ReservationSummary
from app.schemas.payment import PaymentCreate, PaymentRead, PaymentListItem, PaginatedPayments
from app.schemas.admin import PolicyRead, PolicyCreate, AuditLogRead
from app.schemas.room import RoomTypeRead, RoomTypeCreate
from typing import Optional
from app.permissions.deps import require_permission
from app.services.user_service import create_user_admin, update_user_admin
from app.services.audit_service import log_action
from app.permissions.casbin_enforcer import get_enforcer
from app.services.reservation_service import create_admin_reservation, calculate_price
from app.services.room_service import upload_image_to_cloudinary
from app.utils.date_utils import get_el_salvador_now, get_el_salvador_today

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/ping", dependencies=[Depends(require_permission("admin", "read"))])
def admin_ping(current_user: User = Depends(get_current_user)):
    return {"message": "Acceso admin OK", "user": current_user.email}

@router.get("/dashboard-stats", dependencies=[Depends(require_permission("admin", "read"))])
def get_dashboard_stats(db: Session = Depends(get_db)):
    from datetime import timedelta
    now = get_el_salvador_now()
    today = get_el_salvador_today()
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)
    next_week = today + timedelta(days=7)

    # Helper for growth
    def calc_growth(current, previous):
        if previous == 0:
            return 100 if current > 0 else 0
        return round(((current - previous) / previous) * 100, 1)

    # 1. Basic Totals & KPIs
    total_users = db.query(User).filter(User.is_active == True).count()
    total_rooms = db.query(Room).filter(Room.is_active == True, Room.is_deleted == False).count()
    
    # 2. Revenue & Advanced Metrics (ADR, RevPAR)
    rev_total = db.query(func.sum(Payment.amount)).filter(Payment.status == "completed").scalar() or 0
    rev_last_30 = db.query(func.sum(Payment.amount)).filter(Payment.status == "completed", Payment.created_at >= thirty_days_ago).scalar() or 0
    rev_prev_30 = db.query(func.sum(Payment.amount)).filter(Payment.status == "completed", Payment.created_at >= sixty_days_ago, Payment.created_at < thirty_days_ago).scalar() or 0
    
    # Count of occupied room-nights in last 30 days for ADR
    # Usamos DATEDIFF para SQL Server a través de func.datediff
    raw_occupied_nights = db.query(
        func.sum(func.datediff(text('day'), Reservation.check_in, Reservation.check_out))
    ).filter(
        Reservation.status == "confirmed",
        Reservation.is_deleted == False,
        Reservation.check_in >= thirty_days_ago
    ).scalar() or 1 # Avoid div by zero
    
    occupied_nights_30 = int(raw_occupied_nights)
    if occupied_nights_30 <= 0: occupied_nights_30 = 1

    adr = float(rev_last_30) / occupied_nights_30
    rev_par = float(rev_last_30) / (total_rooms * 30) if total_rooms > 0 else 0

    # 3. Occupancy Distribution (Live)
    from app.services import system_settings_service as sss
    from datetime import time, datetime
    
    checkin_time = sss.get_checkin_time(db)
    checkout_time = sss.get_checkout_time(db)

    try:
        ci_h, ci_m = map(int, checkin_time.split(":"))
        checkin_t = time(ci_h, ci_m)
    except Exception:
        checkin_t = time(15, 0)

    try:
        co_h, co_m = map(int, checkout_time.split(":"))
        checkout_t = time(co_h, co_m)
    except Exception:
        checkout_t = time(11, 0)

    now_local = get_el_salvador_now().replace(tzinfo=None)
    
    # Obtener reservas confirmadas que tocan el día de hoy
    reservations_today = db.query(Reservation).filter(
        Reservation.status == "confirmed",
        Reservation.is_deleted == False,
        Reservation.check_in <= today,
        Reservation.check_out >= today
    ).all()

    occupied_now_set = set()
    for res in reservations_today:
        start_dt = datetime.combine(res.check_in, checkin_t)
        end_dt = datetime.combine(res.check_out, checkout_t)
        if start_dt <= now_local < end_dt:
            occupied_now_set.add(res.room_id)
            
    occupied_now = len(occupied_now_set)
    
    # 4. Operations (Next 7 Days) - Solo Confirmadas
    arrivals_next_7 = db.query(Reservation).filter(Reservation.check_in >= today, Reservation.check_in <= next_week, Reservation.status == "confirmed", Reservation.is_deleted == False).count()
    departures_next_7 = db.query(Reservation).filter(Reservation.check_out >= today, Reservation.check_out <= next_week, Reservation.status == "confirmed", Reservation.is_deleted == False).count()

    # Historical (30 days) - Ajustado a zona horaria El Salvador (-6h)
    # Usamos subquery para evitar errores de GROUP BY en SQL Server
    sub = db.query(
        cast(func.dateadd(text('hour'), -6, Payment.created_at), Date).label("day"),
        Payment.amount
    ).filter(
        Payment.status == "completed",
        Payment.created_at >= thirty_days_ago
    ).subquery()

    chart_data_raw = db.query(
        sub.c.day,
        func.sum(sub.c.amount).label("total")
    ).group_by(sub.c.day).all()
    
    revenue_map = {str(row.day): float(row.total) for row in chart_data_raw}
    
    # Forecast (Next 7 days based on pending/confirmed reservations)
    reservations_next_7 = db.query(Reservation).options(
        selectinload(Reservation.payments),
        selectinload(Reservation.incidental_charges)
    ).filter(
        Reservation.status.in_(["pending", "confirmed"]),
        Reservation.check_in >= today,
        Reservation.check_in <= next_week,
        Reservation.is_deleted == False
    ).all()

    from collections import defaultdict
    from decimal import Decimal
    forecast_accrual_map = defaultdict(float)
    forecast_cash_map = defaultdict(float)

    for res in reservations_next_7:
        day_str = str(res.check_in)
        # Accrual (Devengado): just lodging total_cost
        forecast_accrual_map[day_str] += float(res.total_cost or 0)
        
        # Cash (Caja): pending balance to collect
        from app.services.reservation_service import calculate_grand_total
        grand_total = calculate_grand_total(res, db)
        
        raw_paid = sum(p.amount for p in res.payments if p.status == "completed")
        
        pending = max(Decimal("0.0"), grand_total - Decimal(str(raw_paid)))
        forecast_cash_map[day_str] += float(pending)

    full_trend = []
    # Combine Historical
    for i in range(29, -1, -1):
        d = (today - timedelta(days=i))
        d_str = d.isoformat()
        amount_val = revenue_map.get(d_str, 0.0)
        full_trend.append({
            "date": d_str, 
            "amount": amount_val, 
            "amount_cash": amount_val, 
            "type": "actual"
        })
    
    # Add Forecast
    for i in range(1, 8):
        d = (today + timedelta(days=i))
        d_str = d.isoformat()
        full_trend.append({
            "date": d_str, 
            "amount": forecast_accrual_map.get(d_str, 0.0), 
            "amount_cash": forecast_cash_map.get(d_str, 0.0), 
            "type": "forecast"
        })

    # 6. Market Mix (Revenue by Room Type) - Compute both Gross and Net room revenue allocations!
    from decimal import Decimal
    from app.services.system_settings_service import get_tax_iva, get_tax_tourism
    iva_rate = Decimal(str(get_tax_iva(db)))
    tourism_rate = Decimal(str(get_tax_tourism(db)))
    room_tax_factor = Decimal("1.0") + iva_rate + tourism_rate

    completed_payments_30 = db.query(Payment).options(
        selectinload(Payment.reservation).selectinload(Reservation.room).selectinload(Room.room_type),
        selectinload(Payment.reservation).selectinload(Reservation.incidental_charges)
    ).filter(
        Payment.status == "completed",
        Payment.created_at >= thirty_days_ago
    ).all()

    from collections import defaultdict
    mix_gross_map = defaultdict(Decimal)
    mix_net_map = defaultdict(Decimal)

    # Initialize all active room types
    active_room_types = db.query(RoomType.name).filter(RoomType.is_deleted == False).all()
    for rt in active_room_types:
        mix_gross_map[rt.name] = Decimal("0.0")
        mix_net_map[rt.name] = Decimal("0.0")

    for pay in completed_payments_30:
        res = pay.reservation
        if not res or not res.room or not res.room.room_type:
            continue
        
        rt_name = res.room.room_type.name
        amount = Decimal(str(pay.amount or 0))

        mix_gross_map[rt_name] += amount

        # Net lodging calculation (pro-rata based on reservation base values)
        room_base = Decimal(str(res.subtotal)) if res.subtotal is not None else Decimal(str(res.total_cost or 0)) / room_tax_factor
        room_iva = Decimal(str(res.tax_iva)) if res.tax_iva is not None else room_base * iva_rate
        room_tourism = Decimal(str(res.tax_tourism)) if res.tax_tourism is not None else room_base * tourism_rate
        room_total = room_base + room_iva + room_tourism

        extras_base = Decimal(str(res.extras_total or 0))
        extras_iva = extras_base * iva_rate
        extras_total = extras_base + extras_iva

        inc_base = Decimal(str(res.incidentals_total or 0))
        inc_iva = Decimal("0.0")
        if res.incidental_charges:
            for ch in res.incidental_charges:
                if ch.payment_status != "waived" and ch.apply_tax:
                    inc_iva += Decimal(str(ch.total_amount or 0)) * iva_rate
        inc_total = inc_base + inc_iva

        grand_total = room_total + extras_total + inc_total
        if grand_total <= 0:
            grand_total = Decimal("1.0")

        prop_room = room_base / grand_total
        p_room_net = amount * prop_room
        mix_net_map[rt_name] += p_room_net

    mix_data = [
        {
            "label": k,
            "value": float(v),
            "net_value": float(mix_net_map[k])
        } for k, v in mix_gross_map.items()
    ]

    return {
        "kpis": {
            "revenue": {
                "total": float(rev_last_30), 
                "historical_total": float(rev_total),
                "growth": calc_growth(float(rev_last_30), float(rev_prev_30)),
                "adr": round(adr, 2),
                "revpar": round(rev_par, 2),
                "revpar_growth": calc_growth(float(rev_par), float(rev_prev_30 / (total_rooms * 30) if total_rooms > 0 else 0)),
                "price_efficiency": round((adr / float(db.query(func.avg(Room.base_price)).filter(Room.is_active == True, Room.is_deleted == False).scalar() or 1)) * 100, 1)
            },
            "rooms": {
                "total": total_rooms,
                "occupied": occupied_now,
                "available": max(0, total_rooms - occupied_now),
                "arrivals_7d": arrivals_next_7,
                "departures_7d": departures_next_7
            },
            "users": {
                "total": total_users,
                "growth": 0 # Simplified for now
            },
            "reservations": {
                "total": db.query(Reservation).filter(Reservation.is_deleted == False).count(),
                "growth": 0
            }
        },
        "revenue_trend": full_trend,
        "market_mix": mix_data
    }

@router.get("/reservations", response_model=list[ReservationListItem], dependencies=[Depends(require_permission("reservations", "read"))])
def list_all_reservations(
    db: Session = Depends(get_db),
    room_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(Reservation).options(
        selectinload(Reservation.room),
        selectinload(Reservation.user).selectinload(User.profile),
        selectinload(Reservation.payments),
        selectinload(Reservation.extras),
        selectinload(Reservation.incidental_charges)
    ).filter(Reservation.is_deleted == False)
    
    if room_id:
        query = query.filter(Reservation.room_id == room_id)
        
    reservations = (
        query.order_by(Reservation.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return reservations

@router.get("/recent-reservations", response_model=list[ReservationSummary], dependencies=[Depends(require_permission("reservations", "read"))])
def get_recent_reservations(
    db: Session = Depends(get_db),
    limit: int = Query(default=6, ge=1, le=50),
):
    """
    Endpoint ultra-liviano para obtener las reservaciones más recientes en el Dashboard,
    evitando cargar relaciones costosas.
    """
    reservations = (
        db.query(Reservation)
        .options(
            selectinload(Reservation.user).selectinload(User.profile),
            selectinload(Reservation.room)
        )
        .filter(Reservation.is_deleted == False)
        .order_by(Reservation.created_at.desc())
        .limit(limit)
        .all()
    )
    return reservations

@router.post("/reservations", response_model=ReservationRead, status_code=201, dependencies=[Depends(require_permission("reservations", "create"))])
def create_reservation_admin(
    data: AdminReservationCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reservation = create_admin_reservation(db, data)
    
    log_action(
        db, user_id=current_user.id, resource="reservations", action="create",
        method="POST", path="/admin/reservations", status_code=201, request=request,
        metadata={"created_reservation_id": reservation.id},
    )
    return reservation

@router.put("/reservations/{res_id}", response_model=ReservationRead, dependencies=[Depends(require_permission("reservations", "update"))])
def update_reservation_admin(
    res_id: int,
    data: AdminReservationUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from app.services.reservation_service import update_reservation as service_update_reservation
    
    reservation = db.query(Reservation).options(selectinload(Reservation.room)).filter(Reservation.id == res_id, Reservation.is_deleted == False).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    updated_res = service_update_reservation(db, reservation, data)

    log_action(
        db, user_id=current_user.id, resource="reservations", action="update",
        method="PUT", path=f"/admin/reservations/{res_id}", status_code=200, request=request,
        metadata={"updated_reservation_id": res_id},
    )
    return updated_res

@router.delete("/reservations/{res_id}", status_code=204, dependencies=[Depends(require_permission("reservations", "delete"))])
def delete_admin_reservation(
    res_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    res = db.query(Reservation).filter(Reservation.id == res_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    if res.status == "confirmed":
        raise HTTPException(
            status_code=400, 
            detail="No se puede eliminar una reservación Confirmada (Pagada) para mantener el historial fiscal. Cáncela si es necesario."
        )

    res.is_deleted = True
    db.commit()

    log_action(db, user_id=current_user.id, resource="reservations", action="delete",
               method="DELETE", path=f"/admin/reservations/{res_id}", status_code=204, request=request,
               metadata={"reservation_id": res_id})
    return

@router.post("/reservations/{res_id}/pay", response_model=PaymentRead, status_code=200, dependencies=[Depends(require_permission("reservations", "update"))])
def pay_reservation_admin(
    res_id: int,
    data: PaymentCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if data.reservation_id != res_id:
        raise HTTPException(status_code=400, detail="El ID en el body no coincide con la ruta")

    from app.models.extra_amenity import ReservationExtraAmenity
    from app.models.incidental_charge import IncidentalCharge
    reservation = db.query(Reservation).options(
        selectinload(Reservation.room), 
        selectinload(Reservation.user),
        selectinload(Reservation.extras).selectinload(ReservationExtraAmenity.extra_amenity),
        selectinload(Reservation.incidental_charges)
    ).filter(
        Reservation.id == res_id,
        Reservation.is_deleted == False
    ).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada o ha sido eliminada por otro administrador")
        
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="Esta reservación está cancelada")

    from sqlalchemy import func
    from decimal import Decimal
    raw_total_paid = db.query(func.sum(Payment.amount)).filter(
        Payment.reservation_id == res_id, 
        Payment.status == "completed"
    ).scalar() or 0.0

    total_paid = Decimal(str(raw_total_paid))
    from app.services.reservation_service import calculate_grand_total
    grand_total = calculate_grand_total(reservation, db)
    balance = grand_total - total_paid

    if balance <= 0:
        raise HTTPException(status_code=400, detail="Esta reservación ya ha sido pagada en su totalidad")
        
    if Decimal(str(data.amount)) <= 0:
        raise HTTPException(status_code=400, detail="El monto del pago debe ser mayor a cero")

    profile = reservation.user.profile if reservation.user else None
    
    # Construir dirección completa
    address_parts = []
    if profile:
        if profile.address_complement: address_parts.append(profile.address_complement)
        if profile.municipality: address_parts.append(profile.municipality)
        if profile.department: address_parts.append(profile.department)
        if profile.country: address_parts.append(profile.country)
    
    full_address = ", ".join(address_parts) if address_parts else "EL SALVADOR"
    
    # Generar receipt data de forma itemizada y dinámica
    from app.services.system_settings_service import get_tax_iva, get_tax_tourism
    from app.services.payment_allocation_service import allocate_payment_items
    
    iva_rate = float(get_tax_iva(db))
    tourism_rate = float(get_tax_tourism(db))
    allocated_items = allocate_payment_items(db, reservation, Decimal(str(data.amount)))
    
    room_base = sum(item["total_amount"] for item in allocated_items if item["type"] == "room")
    room_iva = sum(item["tax"] for item in allocated_items if item["type"] == "room")
    room_tourism = sum(item["tourism"] for item in allocated_items if item["type"] == "room")
    
    extras_base = sum(item["total_amount"] for item in allocated_items if item["type"] == "extra")
    extras_iva = sum(item["tax"] for item in allocated_items if item["type"] == "extra")
    
    incidentals_base = sum(item["total_amount"] for item in allocated_items if item["type"] == "incidental")
    incidentals_iva = sum(item["tax"] for item in allocated_items if item["type"] == "incidental")

    receipt_data = {
        "company": "Hotel AFE",
        "date": get_el_salvador_now().isoformat(),
        "customer": f"{profile.first_name} {profile.last_name}" if profile else (reservation.user.email if reservation.user else "Admin Processed"),
        "customer_email": reservation.user.email if reservation.user else None,
        "customer_address": full_address,
        "customer_phone": profile.phone if profile else "---",
        "document_number": profile.document_number if profile else "---",
        "receipt_type": data.receipt_type,
        "reservation_id": reservation.unique_id,
        "room_number": reservation.room.number,
        "room_type": reservation.room.type,
        "check_in": reservation.check_in.isoformat(),
        "check_out": reservation.check_out.isoformat(),
        "amount_paid": str(data.amount),
        "method": data.method,
        "tax_iva_rate": iva_rate,
        "tax_tourism_rate": tourism_rate,
        "room_base": float(room_base),
        "room_iva": float(room_iva),
        "room_tourism": float(room_tourism),
        "extras_base": float(extras_base),
        "extras_iva": float(extras_iva),
        "incidentals_base": float(incidentals_base),
        "incidentals_iva": float(incidentals_iva),
        "items": allocated_items,
        "extras": [ex for ex in allocated_items if ex["type"] == "extra"],
        "incidentals": [inc for inc in allocated_items if inc["type"] == "incidental"]
    }

    if data.receipt_type == "fiscal_credit" and profile:
        receipt_data.update({
            "nit": profile.nit,
            "nrc": profile.nrc,
            "business_name": profile.business_name or f"{profile.first_name} {profile.last_name}",
            "economic_activity": profile.economic_activity
        })

    payment = Payment(
        reservation_id=data.reservation_id,
        amount=data.amount,
        method=data.method,
        status="completed",
        receipt_type=data.receipt_type,
        receipt_data=receipt_data
    )
    db.add(payment)

    # Capturar estado previo antes de modificar
    was_confirmed = reservation.status == "confirmed"

    # Auto-update status if fully paid
    if total_paid + Decimal(str(data.amount)) >= grand_total:
        reservation.status = "confirmed"
        for extra in reservation.extras:
            if extra.payment_status == "pending":
                extra.payment_status = "paid"
        for inc in reservation.incidental_charges:
            if inc.payment_status == "pending":
                inc.payment_status = "paid"
    
    db.commit()
    db.refresh(payment)

    if reservation.user and reservation.user.email:
        from app.utils.date_utils import format_payment_datetime
        first_name = reservation.user.profile.first_name if reservation.user.profile else "Cliente"
        payment_date_fmt = format_payment_datetime()

        # Generar PDF y JSON del DTE (compartido entre ambos emails)
        try:
            pdf_content = generate_receipt_pdf(payment.receipt_data)
        except Exception as e:
            print(f"Error generando PDF para reserva {reservation.unique_id}: {str(e)}")
            pdf_content = None

        try:
            json_content = generate_dte_json(payment.receipt_data)
        except Exception as e:
            print(f"Error generando JSON DTE para reserva {reservation.unique_id}: {str(e)}")
            json_content = None

        # SIEMPRE: enviar comprobante de pago con DTE
        background_tasks.add_task(
            send_payment_receipt_email,
            email=reservation.user.email,
            first_name=first_name,
            reservation_id=reservation.unique_id,
            payment_amount=f"{float(data.amount):.2f}",
            payment_method=data.method,
            payment_date=payment_date_fmt,
            pdf_content=pdf_content,
            json_content=json_content
        )

        # SOLO si la reserva acaba de confirmarse por primera vez
        if not was_confirmed and reservation.status == "confirmed":
            background_tasks.add_task(
                send_reservation_confirmed_email,
                email=reservation.user.email,
                first_name=first_name,
                reservation_id=reservation.unique_id,
                check_in=reservation.check_in.strftime("%d/%m/%Y"),
                check_out=reservation.check_out.strftime("%d/%m/%Y"),
                pdf_content=pdf_content,
                json_content=json_content
            )

    log_action(db, user_id=current_user.id, resource="reservations", action="update",
               method="POST", path=f"/admin/reservations/{res_id}/pay", status_code=200, request=request,
               metadata={"reservation_id": res_id, "payment_id": payment.id})
               
    return payment

@router.post("/reservations/{res_id}/refund", response_model=PaymentRead, dependencies=[Depends(require_permission("reservations", "update"))])
def refund_reservation_balance(
    res_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reservation = db.query(Reservation).options(selectinload(Reservation.room), selectinload(Reservation.user)).filter(
        Reservation.id == res_id,
        Reservation.is_deleted == False
    ).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    from sqlalchemy import func
    from decimal import Decimal
    # Calcular balance actual
    raw_total_paid = db.query(func.sum(Payment.amount)).filter(
        Payment.reservation_id == res_id, 
        Payment.status == "completed"
    ).scalar() or 0.0
    
    total_paid = Decimal(str(raw_total_paid))
    from app.services.reservation_service import calculate_grand_total
    grand_total = calculate_grand_total(reservation, db)
    balance = grand_total - total_paid

    if balance >= 0:
        raise HTTPException(status_code=400, detail="No hay saldo a favor para devolver")

    # El monto a devolver es el balance negativo
    refund_amount = balance 
    
    profile = reservation.user.profile if reservation.user else None
    receipt_data = {
        "company": "Hotel AFE",
        "date": get_el_salvador_now().isoformat(),
        "customer": f"{profile.first_name} {profile.last_name}" if profile else (reservation.user.email if reservation.user else "Admin Refund"),
        "customer_email": reservation.user.email if reservation.user else None,
        "receipt_type": "refund",
        "reservation_id": reservation.unique_id,
        "amount_refunded": str(abs(refund_amount)),
        "method": "refund"
    }

    payment = Payment(
        reservation_id=res_id,
        amount=refund_amount, 
        method="refund",
        status="completed",
        receipt_type="refund",
        receipt_data=receipt_data
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    log_action(db, user_id=current_user.id, resource="reservations", action="refund",
               method="POST", path=f"/admin/reservations/{res_id}/refund", status_code=200, request=request,
               metadata={"reservation_id": res_id, "refund_amount": str(refund_amount)})
               
    # Notificar al cliente sobre el reembolso
    if reservation.user and reservation.user.email:
        first_name = reservation.user.profile.first_name if reservation.user.profile else "Cliente"
        background_tasks.add_task(
            send_refund_processed_email,
            email=reservation.user.email,
            first_name=first_name,
            reservation_id=reservation.unique_id,
            amount=str(abs(refund_amount))
        )

    
    return payment

from app.services.wompi_service import generate_wompi_payment_link

@router.post("/reservations/{res_id}/wompi-link", status_code=200, dependencies=[Depends(require_permission("reservations", "update"))])
async def create_wompi_link_admin(
    res_id: int,
    request: Request,
    redirect_url: str = "http://localhost:5173/admin/reservaciones",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reservation = db.query(Reservation).filter(
        Reservation.id == res_id,
        Reservation.is_deleted == False
    ).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada o ha sido eliminada")
    if reservation.status not in ["pending", "confirmed"]:
        raise HTTPException(status_code=400, detail="La reservación no está en un estado que permita pagos")
        
    from sqlalchemy import func
    from app.models.payment import Payment
    from decimal import Decimal
    raw_total_paid = db.query(func.sum(Payment.amount)).filter(
        Payment.reservation_id == res_id, 
        Payment.status == "completed"
    ).scalar() or 0.0
    
    total_paid = Decimal(str(raw_total_paid))
    from app.services.reservation_service import calculate_grand_total
    grand_total = calculate_grand_total(reservation, db)
    balance = grand_total - total_paid
    
    if balance <= 0:
        raise HTTPException(status_code=400, detail="Esta reservación ya está pagada")

    url = await generate_wompi_payment_link(reservation.unique_id, float(balance), redirect_url)
    return {"url": url}

@router.get("/payments", response_model=PaginatedPayments, dependencies=[Depends(require_permission("payments", "read"))])
def list_all_payments(
    db: Session = Depends(get_db),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    method: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(Payment).options(
        selectinload(Payment.reservation).options(
            selectinload(Reservation.user).selectinload(User.profile),
            selectinload(Reservation.room),
            selectinload(Reservation.incidental_charges)
        )
    )
    
    if start_date:
        query = query.filter(Payment.created_at >= start_date)
    if end_date:
        query = query.filter(Payment.created_at <= end_date)
    if method:
        query = query.filter(Payment.method == method)
    if status:
        query = query.filter(Payment.status == status)
        
    total = query.count()
    payments = query.order_by(Payment.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": payments
    }

@router.get("/payments/{payment_id}", response_model=PaymentRead, dependencies=[Depends(require_permission("payments", "read"))])
def get_payment_detail_admin(
    payment_id: int,
    db: Session = Depends(get_db)
):
    payment = db.query(Payment).options(
        selectinload(Payment.reservation).selectinload(Reservation.user),
        selectinload(Payment.reservation).selectinload(Reservation.room)
    ).filter(Payment.id == payment_id).first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
        
    return payment

from pydantic import BaseModel
class PaymentVerifyRequest(BaseModel):
    action: str  # "approve" | "reject"
    reason: Optional[str] = None

@router.post("/payments/{payment_id}/verify", response_model=PaymentRead, dependencies=[Depends(require_permission("payments", "update"))])
async def verify_payment_admin(
    payment_id: int,
    data: PaymentVerifyRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if data.action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="La acción debe ser 'approve' o 'reject'")

    from app.models.extra_amenity import ReservationExtraAmenity
    payment = db.query(Payment).options(
        selectinload(Payment.reservation).selectinload(Reservation.user).selectinload(User.profile),
        selectinload(Payment.reservation).selectinload(Reservation.room),
        selectinload(Payment.reservation).selectinload(Reservation.extras).selectinload(ReservationExtraAmenity.extra_amenity)
    ).filter(Payment.id == payment_id).first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
        
    if payment.status != "verifying":
        raise HTTPException(status_code=400, detail="El pago no está en estado de verificación")

    reservation = payment.reservation

    if data.action == "approve":
        payment.status = "completed"

        # Capturar estado previo antes de modificar
        was_confirmed = reservation.status == "confirmed"

        # Dispatch payment notification
        from app.services import notification_service as notif_svc
        notif_svc.notify_payment_received(db, reservation, payment.amount)

        # Check if full amount is met
        from sqlalchemy import func
        from decimal import Decimal
        raw_total_paid = db.query(func.sum(Payment.amount)).filter(
            Payment.reservation_id == reservation.id,
            Payment.status == "completed"
        ).scalar() or 0.0

        total_paid = Decimal(str(raw_total_paid)) + Decimal(str(payment.amount))

        from app.services.reservation_service import calculate_grand_total
        grand_total = calculate_grand_total(reservation, db)

        if total_paid >= grand_total:
            reservation.status = "confirmed"
            for extra in reservation.extras:
                if extra.payment_status == "pending":
                    extra.payment_status = "paid"
            for inc in reservation.incidental_charges:
                if inc.payment_status == "pending":
                    inc.payment_status = "paid"
            # Dispatch reservation confirmed notification if applicable
            notif_svc.notify_reservation_confirmed(db, reservation)

        # Notificar al cliente — siempre enviar comprobante de pago
        if reservation.user and reservation.user.email:
            from app.utils.date_utils import format_payment_datetime
            first_name = reservation.user.profile.first_name if reservation.user.profile else "Cliente"
            payment_date_fmt = format_payment_datetime()

            # Generar PDF y JSON del DTE (compartido entre ambos emails)
            try:
                pdf_content = generate_receipt_pdf(payment.receipt_data)
            except Exception as e:
                print(f"Error generando PDF para reserva {reservation.unique_id}: {str(e)}")
                pdf_content = None

            try:
                json_content = generate_dte_json(payment.receipt_data)
            except Exception as e:
                print(f"Error generando JSON DTE para reserva {reservation.unique_id}: {str(e)}")
                json_content = None

            # SIEMPRE: enviar comprobante de pago con DTE
            background_tasks.add_task(
                send_payment_receipt_email,
                email=reservation.user.email,
                first_name=first_name,
                reservation_id=reservation.unique_id,
                payment_amount=f"{float(payment.amount):.2f}",
                payment_method=payment.method or "transfer",
                payment_date=payment_date_fmt,
                pdf_content=pdf_content,
                json_content=json_content
            )

            # SOLO si la reserva acaba de confirmarse por primera vez
            if not was_confirmed and reservation.status == "confirmed":
                background_tasks.add_task(
                    send_reservation_confirmed_email,
                    email=reservation.user.email,
                    first_name=first_name,
                    reservation_id=reservation.unique_id,
                    check_in=reservation.check_in.strftime("%d/%m/%Y"),
                    check_out=reservation.check_out.strftime("%d/%m/%Y"),
                    pdf_content=pdf_content,
                    json_content=json_content
                )
    else:
        # reject
        payment.status = "failed"
        if data.reason:
            # Almacenar motivo en el JSON de receipt_data para que el cliente lo vea
            current_data = dict(payment.receipt_data) if payment.receipt_data else {}
            current_data["rejection_reason"] = data.reason
            payment.receipt_data = current_data

        if reservation.status == "verifying":
            reservation.status = "pending"  # Vuelve a estar pendiente de pago
            
        # Notificar al cliente sobre el rechazo
        if reservation.user and reservation.user.email:
            first_name = reservation.user.profile.first_name if reservation.user.profile else "Cliente"
            background_tasks.add_task(
                send_payment_rejected_email,
                email=reservation.user.email,
                first_name=first_name,
                reservation_id=reservation.unique_id,
                reason=data.reason or "Comprobante ilegible o inválido"
            )

    db.commit()
    db.refresh(payment)
    
    log_action(db, user_id=current_user.id, resource="payments", action=f"verify_{data.action}",
               method="POST", path=f"/admin/payments/{payment_id}/verify", status_code=200, request=request,
               metadata={"payment_id": payment_id})
               
    return payment

@router.post("/payments/{payment_id}/resend-email")
async def resend_payment_email(
    payment_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reenvía el comprobante de pago (DTE) al cliente para un pago completado.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    if payment.status != "completed":
        raise HTTPException(status_code=400, detail="Solo se pueden reenviar correos de pagos completados")

    reservation = payment.reservation
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")

    if not reservation.user or not reservation.user.email:
        raise HTTPException(status_code=400, detail="El cliente no tiene un correo electrónico asociado")

    # Generar PDF del DTE
    try:
        pdf_content = generate_receipt_pdf(payment.receipt_data)
    except Exception as e:
        print(f"Error generando PDF para reenvío (reserva {reservation.unique_id}): {str(e)}")
        pdf_content = None

    # Generar JSON del DTE
    try:
        json_content = generate_dte_json(payment.receipt_data)
    except Exception as e:
        print(f"Error generando JSON DTE para reenvío (reserva {reservation.unique_id}): {str(e)}")
        json_content = None

    first_name = reservation.user.profile.first_name if reservation.user.profile else "Cliente"

    # Reconstruir fecha del pago desde receipt_data o usar la fecha de creación
    receipt_data = payment.receipt_data or {}
    payment_date_raw = receipt_data.get("date", "")
    try:
        from datetime import datetime as dt
        payment_date_fmt = dt.fromisoformat(payment_date_raw.replace("Z", "+00:00")).strftime("%d/%m/%Y %I:%M %p")
    except Exception:
        payment_date_fmt = payment.created_at.strftime("%d/%m/%Y") if payment.created_at else "---"

    # Reenviar comprobante de pago (DTE) — opción A: siempre el comprobante
    background_tasks.add_task(
        send_payment_receipt_email,
        email=reservation.user.email,
        first_name=first_name,
        reservation_id=reservation.unique_id,
        payment_amount=f"{float(payment.amount):.2f}",
        payment_method=payment.method or "card",
        payment_date=payment_date_fmt,
        pdf_content=pdf_content,
        json_content=json_content
    )

    return {"message": "Comprobante de pago (DTE) encolado para reenvío"}


# ----- Amenities Catalog -----

from app.models.amenity import Amenity, AmenityCategory
from app.schemas.amenity import AmenityRead, AmenityCreate, AmenityUpdate, AmenityCategoryRead, AmenityCategoryCreate, AmenityCategoryUpdate

@router.get("/amenity-categories", response_model=list[AmenityCategoryRead], dependencies=[Depends(require_permission("rooms", "read"))])
def get_admin_amenity_categories(db: Session = Depends(get_db)):
    return db.query(AmenityCategory).filter(AmenityCategory.is_deleted == False).order_by(AmenityCategory.name).all()

@router.post("/amenity-categories", response_model=AmenityCategoryRead, status_code=201, dependencies=[Depends(require_permission("rooms", "create"))])
def create_admin_amenity_category(
    data: AmenityCategoryCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    exists = db.query(AmenityCategory).filter(AmenityCategory.name == data.name).first()
    if exists:
        if exists.is_deleted:
            exists.is_deleted = False
            db.commit()
            db.refresh(exists)
            log_action(db, user_id=current_user.id, resource="amenity_categories", action="create (reactivated)",
                       method="POST", path="/admin/amenity-categories", status_code=201, request=request,
                       metadata={"category_name": exists.name})
            return exists
        else:
            raise HTTPException(status_code=400, detail="Esta categoría ya existe.")
    
    new_cat = AmenityCategory(name=data.name)
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    
    log_action(db, user_id=current_user.id, resource="amenity_categories", action="create",
               method="POST", path="/admin/amenity-categories", status_code=201, request=request,
               metadata={"category_name": new_cat.name})
    return new_cat

@router.put("/amenity-categories/{category_id}", response_model=AmenityCategoryRead, dependencies=[Depends(require_permission("rooms", "update"))])
def update_admin_amenity_category(
    category_id: int,
    data: AmenityCategoryUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    cat = db.query(AmenityCategory).filter(AmenityCategory.id == category_id, AmenityCategory.is_deleted == False).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    
    dup = db.query(AmenityCategory).filter(AmenityCategory.name == data.name, AmenityCategory.id != category_id, AmenityCategory.is_deleted == False).first()
    if dup:
        raise HTTPException(status_code=400, detail="Ya existe una categoría con ese nombre.")
    
    cat.name = data.name
    db.commit()
    db.refresh(cat)
    
    log_action(db, user_id=current_user.id, resource="amenity_categories", action="update",
               method="PUT", path=f"/admin/amenity-categories/{category_id}", status_code=200, request=request,
               metadata={"category_id": category_id})
    return cat

@router.delete("/amenity-categories/{category_id}", dependencies=[Depends(require_permission("rooms", "delete"))])
def delete_admin_amenity_category(
    category_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    cat = db.query(AmenityCategory).filter(AmenityCategory.id == category_id, AmenityCategory.is_deleted == False).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    
    cat.is_deleted = True
    db.commit()
    
    log_action(db, user_id=current_user.id, resource="amenity_categories", action="delete",
               method="DELETE", path=f"/admin/amenity-categories/{category_id}", status_code=200, request=request,
               metadata={"category_id": category_id})
    return {"detail": "Categoría eliminada lógicamente"}

@router.get("/amenities", response_model=list[AmenityRead], dependencies=[Depends(require_permission("rooms", "read"))])
def get_admin_amenities(db: Session = Depends(get_db)):
    return db.query(Amenity).filter(Amenity.is_deleted == False).order_by(Amenity.category_id, Amenity.name).all()

@router.post("/amenities", response_model=AmenityRead, status_code=201, dependencies=[Depends(require_permission("rooms", "create"))])
def create_admin_amenity(
    data: AmenityCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    exists = db.query(Amenity).filter(Amenity.name == data.name).first()
    if exists:
        if exists.is_deleted:
            exists.is_deleted = False
            exists.icon = data.icon
            exists.category_id = data.category_id
            db.commit()
            db.refresh(exists)
            log_action(db, user_id=current_user.id, resource="amenities", action="create (reactivated)",
                       method="POST", path="/admin/amenities", status_code=201, request=request,
                       metadata={"amenity_name": exists.name})
            return exists
        else:
            raise HTTPException(status_code=400, detail="Esta amenidad ya existe.")
    
    new_amenity = Amenity(name=data.name, icon=data.icon, category_id=data.category_id)
    db.add(new_amenity)
    db.commit()
    db.refresh(new_amenity)
    
    log_action(db, user_id=current_user.id, resource="amenities", action="create",
               method="POST", path="/admin/amenities", status_code=201, request=request,
               metadata={"amenity_name": new_amenity.name})
    return new_amenity

@router.put("/amenities/{amenity_id}", response_model=AmenityRead, dependencies=[Depends(require_permission("rooms", "update"))])
def update_admin_amenity(
    amenity_id: int,
    data: AmenityUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    amenity = db.query(Amenity).filter(Amenity.id == amenity_id, Amenity.is_deleted == False).first()
    if not amenity:
        raise HTTPException(status_code=404, detail="Amenidad no encontrada")
    
    if data.name is not None:
        # Check for duplicate name
        dup = db.query(Amenity).filter(Amenity.name == data.name, Amenity.id != amenity_id, Amenity.is_deleted == False).first()
        if dup:
            raise HTTPException(status_code=400, detail="Ya existe una amenidad con ese nombre.")
        amenity.name = data.name
    if data.icon is not None:
        amenity.icon = data.icon
    if data.category_id is not None:
        amenity.category_id = data.category_id
    
    db.commit()
    db.refresh(amenity)
    
    log_action(db, user_id=current_user.id, resource="amenities", action="update",
               method="PUT", path=f"/admin/amenities/{amenity_id}", status_code=200, request=request,
               metadata={"amenity_id": amenity_id})
    return amenity

@router.delete("/amenities/{amenity_id}", dependencies=[Depends(require_permission("rooms", "delete"))])
def delete_admin_amenity(
    amenity_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    amenity = db.query(Amenity).filter(Amenity.id == amenity_id).first()
    if not amenity:
        raise HTTPException(status_code=404, detail="Amenidad no encontrada")
    
    amenity.is_deleted = True
    db.commit()
    
    log_action(db, user_id=current_user.id, resource="amenities", action="delete",
               method="DELETE", path=f"/admin/amenities/{amenity_id}", status_code=200, request=request,
               metadata={"deleted_amenity": amenity.name})
    return {"message": "Amenidad eliminada exitosamente"}

# ----- Room Types Catalog -----

@router.get("/room-types", response_model=list[RoomTypeRead], dependencies=[Depends(require_permission("rooms", "read"))])
def get_admin_room_types(db: Session = Depends(get_db)):
    return db.query(RoomType).filter(RoomType.is_deleted == False).all()

@router.post("/room-types", response_model=RoomTypeRead, dependencies=[Depends(require_permission("rooms", "create"))])
def create_admin_room_type(
    data: RoomTypeCreate, 
    request: Request, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    exists = db.query(RoomType).filter(RoomType.name == data.name).first()
    if exists:
        if exists.is_deleted:
            # Si existía y estaba borrado, lo reactivamos
            exists.is_deleted = False
            exists.description = data.description
            db.commit()
            db.refresh(exists)
            log_action(db, user_id=current_user.id, resource="room-types", action="create (reactivated)",
                       method="POST", path="/admin/room-types", status_code=201, request=request,
                       metadata={"room_type_name": exists.name})
            return exists
        else:
            raise HTTPException(status_code=400, detail="Este tipo de habitación ya existe.")
            
    new_type = RoomType(name=data.name, description=data.description)
    db.add(new_type)
    db.commit()
    db.refresh(new_type)
    
    log_action(db, user_id=current_user.id, resource="room-types", action="create",
               method="POST", path="/admin/room-types", status_code=201, request=request,
               metadata={"room_type_name": new_type.name})
    return new_type

@router.delete("/room-types/{type_id}", dependencies=[Depends(require_permission("rooms", "delete"))])
def delete_admin_room_type(
    type_id: int, 
    request: Request, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    rt = db.query(RoomType).filter(RoomType.id == type_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="Tipo de habitación no encontrado")
        
    rt.is_deleted = True
    db.commit()
    
    log_action(db, user_id=current_user.id, resource="room-types", action="delete",
               method="DELETE", path=f"/admin/room-types/{type_id}", status_code=200, request=request,
               metadata={"deleted_type": rt.name})
    return {"message": "Tipo de habitación eliminado exitosamente"}

@router.post("/upload-image", dependencies=[Depends(require_permission("rooms", "create"))])
async def upload_admin_image(
    file: UploadFile = File(...),
):
    return {"url": upload_image_to_cloudinary(file)}

# ----- Usuarios -----


@router.get("/users", response_model=list[UserRead], dependencies=[Depends(require_permission("users", "read"))])
def list_users(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    users = (
        db.query(User)
        .options(selectinload(User.roles), selectinload(User.profile))
        .filter(User.is_active == True)
        .order_by(User.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return users

def _generate_random_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()"
    while True:
        pwd = ''.join(secrets.choice(alphabet) for i in range(length))
        if (any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^&*()" for c in pwd)):
            return pwd

@router.post("/users", response_model=UserRead, status_code=201, dependencies=[Depends(require_permission("users", "create"))])
def create_user(
    user_in: UserCreateAdmin,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Generar contraseña si no se proporciona
    password_to_send = user_in.password
    if not password_to_send:
        password_to_send = _generate_random_password()
        user_in.password = password_to_send

    user = create_user_admin(db, user_in)
    
    # Enviar correo de bienvenida en segundo plano
    background_tasks.add_task(
        send_welcome_email, 
        email=user.email, 
        first_name=user.profile.first_name, 
        password=password_to_send
    )
    log_action(
        db, user_id=current_user.id, resource="users", action="create",
        method="POST", path="/admin/users", status_code=201, request=request,
        metadata={"created_user_id": user.id, "email": user.email},
    )
    return user


@router.get("/users/{user_id}", response_model=UserRead, dependencies=[Depends(require_permission("users", "read"))])
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .options(selectinload(User.roles), selectinload(User.profile))
        .filter(User.id == user_id, User.is_active == True)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


@router.patch("/users/{user_id}", response_model=UserRead, dependencies=[Depends(require_permission("users", "update"))])
def update_user(
    user_id: int,
    data: UserUpdateAdmin,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = update_user_admin(db, user_id, data, current_user_id=current_user.id)
    log_action(
        db, user_id=current_user.id, resource="users", action="update",
        method="PATCH", path=f"/admin/users/{user_id}", status_code=200, request=request,
        metadata={"updated_user_id": user_id},
    )
    return user


@router.delete("/users/{user_id}", status_code=204, dependencies=[Depends(require_permission("users", "delete"))])
def deactivate_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="No puedes desactivar tu propia cuenta.",
        )
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    u.is_active = False
    db.commit()
    log_action(
        db, user_id=current_user.id, resource="users", action="deactivate",
        method="DELETE", path=f"/admin/users/{user_id}", status_code=204, request=request,
        metadata={"deactivated_user_id": user_id},
    )
    return None


# ----- Clientes -----


@router.get("/clients", response_model=list[UserRead], dependencies=[Depends(require_permission("customers", "read"))])
def list_clients(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    # Filtrar solo usuarios con el rol "cliente"
    clients = (
        db.query(User)
        .join(User.roles)
        .options(selectinload(User.roles), selectinload(User.profile))
        .filter(User.is_active == True, Role.name == "cliente")
        .order_by(User.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return clients


@router.get("/clients/{client_id}", response_model=UserRead, dependencies=[Depends(require_permission("customers", "read"))])
def get_client(
    client_id: int,
    db: Session = Depends(get_db),
):
    client = (
        db.query(User)
        .join(User.roles)
        .options(selectinload(User.roles), selectinload(User.profile))
        .filter(User.id == client_id, Role.name == "cliente")
        .first()
    )
    if not client:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return client


@router.post("/clients", response_model=UserRead, status_code=201, dependencies=[Depends(require_permission("customers", "create"))])
def create_client(
    user_in: UserCreateAdmin,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Forzar el rol "cliente"
    cliente_role = db.query(Role).filter(Role.name == "cliente").first()
    if not cliente_role:
        raise HTTPException(status_code=404, detail="Rol 'cliente' no encontrado")
    
    user_in.role_id = cliente_role.id
    
    # Generar contraseña si no se proporciona
    password_to_send = user_in.password
    if not password_to_send:
        password_to_send = _generate_random_password()
        user_in.password = password_to_send

    user = create_user_admin(db, user_in)
    
    # Enviar correo de bienvenida
    background_tasks.add_task(
        send_welcome_email, 
        email=user.email, 
        first_name=user.profile.first_name, 
        password=password_to_send
    )

    log_action(
        db, user_id=current_user.id, resource="customers", action="create",
        method="POST", path="/admin/clients", status_code=201, request=request,
        metadata={"created_client_id": user.id, "email": user.email},
    )
    return user


@router.patch("/clients/{client_id}", response_model=UserRead, dependencies=[Depends(require_permission("customers", "update"))])
def update_client(
    client_id: int,
    data: UserUpdateAdmin,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Verificar que sea un cliente
    user = db.query(User).join(User.roles).filter(User.id == client_id, Role.name == "cliente").first()
    if not user:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
        
    updated_client = update_user_admin(db, client_id, data, current_user_id=current_user.id)
    
    log_action(
        db, user_id=current_user.id, resource="customers", action="update",
        method="PATCH", path=f"/admin/clients/{client_id}", status_code=200, request=request,
        metadata={"updated_client_id": client_id},
    )
    return updated_client


@router.delete("/clients/{client_id}", status_code=204, dependencies=[Depends(require_permission("customers", "delete"))])
def deactivate_client(
    client_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Verificar que sea un cliente
    user = db.query(User).join(User.roles).filter(User.id == client_id, Role.name == "cliente").first()
    if not user:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
        
    user.is_active = False
    db.commit()
    
    log_action(
        db, user_id=current_user.id, resource="customers", action="deactivate",
        method="DELETE", path=f"/admin/clients/{client_id}", status_code=204, request=request,
        metadata={"deactivated_client_id": client_id},
    )
    return None


# ----- Roles -----


@router.get("/roles", response_model=list[RoleRead], dependencies=[Depends(require_permission("roles", "read"))])
def list_roles(db: Session = Depends(get_db)):
    return db.query(Role).all()


@router.post("/roles", response_model=RoleRead, status_code=201, dependencies=[Depends(require_permission("roles", "create"))])
def create_role(
    data: RoleCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Role).filter(Role.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe un rol con ese nombre.")
    role = Role(name=data.name, description=data.description)
    db.add(role)
    db.commit()
    db.refresh(role)
    log_action(
        db, user_id=current_user.id, resource="roles", action="create",
        method="POST", path="/admin/roles", status_code=201, request=request,
        metadata={"role_id": role.id, "name": role.name},
    )
    return role


@router.patch("/roles/{role_id}", response_model=RoleRead, dependencies=[Depends(require_permission("roles", "update"))])
def update_role(
    role_id: int,
    data: RoleUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    
    if role.name in ("admin", "cliente"):
        raise HTTPException(
            status_code=403,
            detail=f"El rol '{role.name}' es un rol del sistema protegido y no puede ser editado."
        )

    if data.name is not None:
        other = db.query(Role).filter(Role.name == data.name, Role.id != role_id).first()
        if other:
            raise HTTPException(status_code=409, detail="Ya existe un rol con ese nombre.")
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    db.commit()
    db.refresh(role)
    log_action(
        db, user_id=current_user.id, resource="roles", action="update",
        method="PATCH", path=f"/admin/roles/{role_id}", status_code=200, request=request,
        metadata={"role_id": role_id},
    )
    return role


@router.delete("/roles/{role_id}", status_code=204, dependencies=[Depends(require_permission("roles", "delete"))])
def delete_role(
    role_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    
    if role.name in ("admin", "cliente"):
        raise HTTPException(
            status_code=403,
            detail=f"El rol '{role.name}' es un rol del sistema protegido y no puede ser eliminado."
        )

    count = db.query(UserRole).filter(UserRole.role_id == role_id).count()
    if count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"No se puede eliminar: {count} usuario(s) tienen asignado este rol.",
        )
    db.delete(role)
    db.commit()
    log_action(
        db, user_id=current_user.id, resource="roles", action="delete",
        method="DELETE", path=f"/admin/roles/{role_id}", status_code=204, request=request,
        metadata={"role_id": role_id, "name": role.name},
    )
    return None


# ----- Permisos (Casbin) -----

from app.permissions.utils import RESOURCES as PERM_RESOURCES, ACTIONS as PERM_ACTIONS


from app.models.user import PermissionResource
from pydantic import BaseModel

class ResourceCreate(BaseModel):
    name: str

@router.get(
    "/permissions/metadata",
    response_model=dict,
    dependencies=[Depends(require_permission("permissions", "read"))],
)
def get_permissions_metadata(db: Session = Depends(get_db)):
    """
    Devuelve recursos y acciones válidos para políticas (fuente dinámica en db).
    Incluye '*' para políticas wildcard en Casbin.
    """
    db_resources = db.query(PermissionResource).order_by(PermissionResource.name).all()
    resource_names = [r.name for r in db_resources]
    return {
        "resources": [*resource_names, "*"],
        "actions": [*PERM_ACTIONS, "*"],
    }

@router.post("/permissions/resources", status_code=201, dependencies=[Depends(require_permission("permissions", "create"))])
def create_permission_resource(
    data: ResourceCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre del recurso es requerido.")
    existing = db.query(PermissionResource).filter(PermissionResource.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail="El recurso ya existe.")
    new_res = PermissionResource(name=name)
    db.add(new_res)
    db.commit()
    log_action(
        db, user_id=current_user.id, resource="permissions", action="create_resource",
        method="POST", path="/admin/permissions/resources", status_code=201, request=request,
        metadata={"resource_name": name},
    )
    return {"name": name}

@router.delete("/permissions/resources/{name}", status_code=204, dependencies=[Depends(require_permission("permissions", "delete"))])
def delete_permission_resource(
    name: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = db.query(PermissionResource).filter(PermissionResource.name == name).first()
    if not res:
        raise HTTPException(status_code=404, detail="Recurso no encontrado.")
    
    enforcer = get_enforcer()
    enforcer.remove_filtered_policy(1, name)
    enforcer.save_policy()

    db.delete(res)
    db.commit()
    log_action(
        db, user_id=current_user.id, resource="permissions", action="delete_resource",
        method="DELETE", path=f"/admin/permissions/resources/{name}", status_code=204, request=request,
        metadata={"resource_name": name},
    )
    return None


@router.get("/permissions", response_model=list[PolicyRead], dependencies=[Depends(require_permission("permissions", "read"))])
def list_permissions(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    enforcer = get_enforcer()
    policies = enforcer.get_policy()
    slice_ = policies[offset : offset + limit]
    return [PolicyRead(sub=p[0], obj=p[1], act=p[2]) for p in slice_]


@router.post("/permissions", response_model=PolicyRead, status_code=201, dependencies=[Depends(require_permission("permissions", "create"))])
def add_permission(
    data: PolicyCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforcer = get_enforcer()
    if enforcer.has_policy(data.sub, data.obj, data.act):
        raise HTTPException(status_code=409, detail="La política ya existe.")
    enforcer.add_policy(data.sub, data.obj, data.act)
    enforcer.save_policy()
    log_action(
        db, user_id=current_user.id, resource="permissions", action="create",
        method="POST", path="/admin/permissions", status_code=201, request=request,
        metadata={"sub": data.sub, "obj": data.obj, "act": data.act},
    )
    return PolicyRead(sub=data.sub, obj=data.obj, act=data.act)


@router.delete("/permissions", status_code=204, dependencies=[Depends(require_permission("permissions", "delete"))])
def remove_permission(
    request: Request,
    sub: str = Query(...), obj: str = Query(...), act: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.name == sub).first()
    if role:
        user_ids_with_role = [ur.user_id for ur in db.query(UserRole).filter(UserRole.role_id == role.id).all()]
        if len(user_ids_with_role) == 1 and user_ids_with_role[0] == current_user.id:
            raise HTTPException(
                status_code=400,
                detail="No puedes eliminar políticas del único rol con el que cuentas.",
            )
    enforcer = get_enforcer()
    if not enforcer.has_policy(sub, obj, act):
        raise HTTPException(status_code=404, detail="Política no encontrada.")
    enforcer.remove_policy(sub, obj, act)
    enforcer.save_policy()
    log_action(
        db, user_id=current_user.id, resource="permissions", action="delete",
        method="DELETE", path="/admin/permissions", status_code=204, request=request,
        metadata={"sub": sub, "obj": obj, "act": act},
    )
    return None


# ----- Bitácora -----


@router.get("/audit-logs", response_model=list[AuditLogRead], dependencies=[Depends(require_permission("audit_logs", "read"))])
def list_audit_logs(
    db: Session = Depends(get_db),
    event_type: str | None = Query(default=None),
    method: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=500, ge=1),
    offset: int = Query(default=0, ge=0),
):
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if event_type:
        q = q.filter(AuditLog.event_type == event_type)
    if method:
        if method.upper() == "UPDATE":
            q = q.filter(AuditLog.method.in_(["PUT", "PATCH"]))
        else:
            q = q.filter(AuditLog.method == method.upper())
    if user_id is not None:
        q = q.filter(AuditLog.user_id == user_id)
    return q.offset(offset).limit(limit).all()


# ────────────────────────────────────────────────────────────────
# Notification Settings (configuración global de notificaciones)
# ────────────────────────────────────────────────────────────────
from app.schemas.notification import NotificationSettingRead, NotificationSettingUpdate
from app.services import notification_service as notif_svc


@router.get("/notification-settings", response_model=list[NotificationSettingRead], dependencies=[Depends(require_permission("admin", "read"))])
def list_notification_settings(
    db: Session = Depends(get_db),
):
    """Lista todas las configuraciones del sistema de notificaciones."""
    return notif_svc.get_all_settings(db)


@router.put("/notification-settings/{key}", response_model=NotificationSettingRead, dependencies=[Depends(require_permission("admin", "update"))])
def update_notification_setting(
    key: str,
    body: NotificationSettingUpdate,
    db: Session = Depends(get_db),
):
    """Actualiza una configuración del sistema de notificaciones."""
    updated = notif_svc.update_setting(db, key, body.value)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' no encontrado.")
    return updated


# ═══════════════════════════════════════════════════════════════
# AMENIDADES EXTRAS CON COSTO
# ═══════════════════════════════════════════════════════════════
from app.models.extra_amenity import ExtraAmenityCategory, ExtraAmenity, ReservationExtraAmenity
from app.schemas.extra_amenity import (
    ExtraAmenityCategoryCreate, ExtraAmenityCategoryUpdate, ExtraAmenityCategoryRead,
    ExtraAmenityCreate, ExtraAmenityUpdate, ExtraAmenityRead,
    ReservationExtraCreate, ReservationExtraRead
)

# ── Categorías ────────────────────────────────────────────────

@router.get("/extra-amenity-categories", response_model=list[ExtraAmenityCategoryRead],
            dependencies=[Depends(require_permission("admin", "read"))])
def list_extra_amenity_categories(db: Session = Depends(get_db)):
    return db.query(ExtraAmenityCategory).filter(ExtraAmenityCategory.is_deleted == False).order_by(ExtraAmenityCategory.name).all()

@router.post("/extra-amenity-categories", response_model=ExtraAmenityCategoryRead, status_code=201,
             dependencies=[Depends(require_permission("admin", "create"))])
def create_extra_amenity_category(body: ExtraAmenityCategoryCreate, db: Session = Depends(get_db)):
    existing = db.query(ExtraAmenityCategory).filter(ExtraAmenityCategory.name == body.name, ExtraAmenityCategory.is_deleted == False).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")
    cat = ExtraAmenityCategory(**body.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat

@router.patch("/extra-amenity-categories/{cat_id}", response_model=ExtraAmenityCategoryRead,
              dependencies=[Depends(require_permission("admin", "update"))])
def update_extra_amenity_category(cat_id: int, body: ExtraAmenityCategoryUpdate, db: Session = Depends(get_db)):
    cat = db.query(ExtraAmenityCategory).filter(ExtraAmenityCategory.id == cat_id, ExtraAmenityCategory.is_deleted == False).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada.")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(cat, field, val)
    db.commit()
    db.refresh(cat)
    return cat

@router.delete("/extra-amenity-categories/{cat_id}", status_code=204,
               dependencies=[Depends(require_permission("admin", "delete"))])
def delete_extra_amenity_category(cat_id: int, db: Session = Depends(get_db)):
    cat = db.query(ExtraAmenityCategory).filter(ExtraAmenityCategory.id == cat_id, ExtraAmenityCategory.is_deleted == False).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada.")
    cat.is_deleted = True
    db.commit()

# ── Catálogo de Extras ────────────────────────────────────────

@router.get("/extra-amenities", response_model=list[ExtraAmenityRead],
            dependencies=[Depends(require_permission("admin", "read"))])
def list_extra_amenities(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = db.query(ExtraAmenity).filter(ExtraAmenity.is_deleted == False)
    if not include_inactive:
        q = q.filter(ExtraAmenity.is_active == True)
    return q.order_by(ExtraAmenity.name).all()

@router.post("/extra-amenities", response_model=ExtraAmenityRead, status_code=201,
             dependencies=[Depends(require_permission("admin", "create"))])
def create_extra_amenity(body: ExtraAmenityCreate, db: Session = Depends(get_db)):
    extra = ExtraAmenity(**body.model_dump())
    db.add(extra)
    db.commit()
    db.refresh(extra)
    return extra

@router.post("/extra-amenities/{extra_id}/upload-image", response_model=ExtraAmenityRead,
             dependencies=[Depends(require_permission("admin", "update"))])
def upload_extra_amenity_image(extra_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    extra = db.query(ExtraAmenity).filter(ExtraAmenity.id == extra_id, ExtraAmenity.is_deleted == False).first()
    if not extra:
        raise HTTPException(status_code=404, detail="Extra no encontrado.")
    extra.image_url = upload_image_to_cloudinary(file)
    db.commit()
    db.refresh(extra)
    return extra

@router.patch("/extra-amenities/{extra_id}", response_model=ExtraAmenityRead,
              dependencies=[Depends(require_permission("admin", "update"))])
def update_extra_amenity(extra_id: int, body: ExtraAmenityUpdate, db: Session = Depends(get_db)):
    extra = db.query(ExtraAmenity).filter(ExtraAmenity.id == extra_id, ExtraAmenity.is_deleted == False).first()
    if not extra:
        raise HTTPException(status_code=404, detail="Extra no encontrado.")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(extra, field, val)
    db.commit()
    db.refresh(extra)
    return extra

@router.delete("/extra-amenities/{extra_id}", status_code=204,
               dependencies=[Depends(require_permission("admin", "delete"))])
def delete_extra_amenity(extra_id: int, db: Session = Depends(get_db)):
    extra = db.query(ExtraAmenity).filter(ExtraAmenity.id == extra_id, ExtraAmenity.is_deleted == False).first()
    if not extra:
        raise HTTPException(status_code=404, detail="Extra no encontrado.")
    extra.is_deleted = True
    db.commit()

# ── Extras en Reservaciones (flujo Admin) ────────────────────

@router.post("/reservations/{res_id}/extras", response_model=ReservationExtraRead, status_code=201,
             dependencies=[Depends(require_permission("admin", "create"))])
def add_extra_to_reservation(res_id: int, body: ReservationExtraCreate, db: Session = Depends(get_db)):
    """
    Agrega un servicio extra a una reservación existente.
    DISEÑO: NO modifica reservation.total_cost ni reservation.status.
    El extra tiene su propio payment_status independiente.
    """
    reservation = db.query(Reservation).filter(Reservation.id == res_id, Reservation.is_deleted == False).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada.")
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="No se pueden agregar extras a una reservación cancelada.")

    extra = db.query(ExtraAmenity).filter(ExtraAmenity.id == body.extra_amenity_id, ExtraAmenity.is_active == True, ExtraAmenity.is_deleted == False).first()
    if not extra:
        raise HTTPException(status_code=404, detail="Amenidad extra no encontrada o inactiva.")

    from decimal import Decimal
    unit_price = Decimal(str(extra.price))
    quantity = body.quantity
    total_price = unit_price * quantity

    pivot = ReservationExtraAmenity(
        reservation_id=res_id,
        extra_amenity_id=extra.id,
        quantity=quantity,
        unit_price=unit_price,
        total_price=total_price,
        payment_status="pending",
        notes=body.notes
    )
    db.add(pivot)

    # Actualizar extras_total (NO afecta total_cost ni status)
    from sqlalchemy import func as sqlfunc
    db.flush()
    new_extras_total = db.query(sqlfunc.sum(ReservationExtraAmenity.total_price)).filter(
        ReservationExtraAmenity.reservation_id == res_id
    ).scalar() or Decimal("0")
    reservation.extras_total = new_extras_total

    db.commit()
    db.refresh(pivot)
    return pivot

@router.delete("/reservations/{res_id}/extras/{pivot_id}", status_code=204,
               dependencies=[Depends(require_permission("admin", "delete"))])
def remove_extra_from_reservation(res_id: int, pivot_id: int, db: Session = Depends(get_db)):
    """Quita un extra de una reservación y recalcula extras_total."""
    pivot = db.query(ReservationExtraAmenity).filter(
        ReservationExtraAmenity.id == pivot_id,
        ReservationExtraAmenity.reservation_id == res_id
    ).first()
    if not pivot:
        raise HTTPException(status_code=404, detail="Extra no encontrado en esta reservación.")
    if pivot.payment_status == "paid":
        raise HTTPException(status_code=400, detail="No se puede eliminar un extra ya pagado.")

    db.delete(pivot)

    from decimal import Decimal
    from sqlalchemy import func as sqlfunc
    db.flush()
    new_extras_total = db.query(sqlfunc.sum(ReservationExtraAmenity.total_price)).filter(
        ReservationExtraAmenity.reservation_id == res_id
    ).scalar() or Decimal("0")

    reservation = db.query(Reservation).filter(Reservation.id == res_id).first()
    if reservation:
        reservation.extras_total = new_extras_total

    db.commit()

@router.patch("/reservations/{res_id}/extras/{pivot_id}/pay", response_model=ReservationExtraRead,
              dependencies=[Depends(require_permission("admin", "update"))])
def mark_extra_as_paid(res_id: int, pivot_id: int, db: Session = Depends(get_db)):
    """
    Marca un extra como pagado.
    IMPORTANTE: Nunca modifica reservation.status.
    """
    pivot = db.query(ReservationExtraAmenity).filter(
        ReservationExtraAmenity.id == pivot_id,
        ReservationExtraAmenity.reservation_id == res_id
    ).first()
    if not pivot:
        raise HTTPException(status_code=404, detail="Extra no encontrado.")
    if pivot.payment_status == "paid":
        raise HTTPException(status_code=400, detail="Este extra ya está marcado como pagado.")

    pivot.payment_status = "paid"
    db.commit()
    db.refresh(pivot)
    return pivot


# ----- Incidental Charges & Categories -----

from app.models.incidental_charge import IncidentalChargeCategory, IncidentalCharge
from app.schemas.incidental_charge import (
    IncidentalChargeCategoryRead,
    IncidentalChargeCategoryCreate,
    IncidentalChargeCategoryUpdate,
    IncidentalChargeRead,
    IncidentalChargeCreate,
    IncidentalChargeUpdate,
    IncidentalChargeWaive
)

def recalculate_reservation_incidentals_total(reservation: Reservation, db: Session):
    from sqlalchemy import func
    from decimal import Decimal
    total = db.query(func.sum(IncidentalCharge.total_amount)).filter(
        IncidentalCharge.reservation_id == reservation.id,
        IncidentalCharge.payment_status != "waived"
    ).scalar() or Decimal("0")
    reservation.incidentals_total = total
    db.flush()
    return total

@router.get("/incidental-categories", response_model=list[IncidentalChargeCategoryRead], dependencies=[Depends(require_permission("incidentals", "read"))])
def get_admin_incidental_categories(db: Session = Depends(get_db)):
    """Lista todas las categorías de cargos incidentales no eliminadas."""
    return db.query(IncidentalChargeCategory).filter(IncidentalChargeCategory.is_deleted == False).order_by(IncidentalChargeCategory.name).all()

@router.post("/incidental-categories", response_model=IncidentalChargeCategoryRead, status_code=201, dependencies=[Depends(require_permission("incidentals", "create"))])
def create_admin_incidental_category(
    data: IncidentalChargeCategoryCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Crea una nueva categoría de cargo incidental."""
    exists = db.query(IncidentalChargeCategory).filter(IncidentalChargeCategory.name == data.name).first()
    if exists:
        if exists.is_deleted:
            exists.is_deleted = False
            exists.description = data.description
            exists.icon = data.icon
            exists.is_active = True
            db.commit()
            db.refresh(exists)
            log_action(db, user_id=current_user.id, resource="incidental_charge_categories", action="create (reactivated)",
                       method="POST", path="/admin/incidental-categories", status_code=201, request=request,
                       metadata={"category_name": exists.name})
            return exists
        else:
            raise HTTPException(status_code=400, detail="Esta categoría ya existe.")
    
    new_cat = IncidentalChargeCategory(
        name=data.name,
        description=data.description,
        icon=data.icon
    )
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    
    log_action(db, user_id=current_user.id, resource="incidental_charge_categories", action="create",
               method="POST", path="/admin/incidental-categories", status_code=201, request=request,
               metadata={"category_name": new_cat.name})
    return new_cat

@router.put("/incidental-categories/{category_id}", response_model=IncidentalChargeCategoryRead, dependencies=[Depends(require_permission("incidentals", "update"))])
def update_admin_incidental_category(
    category_id: int,
    data: IncidentalChargeCategoryUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Actualiza una categoría de cargo incidental."""
    cat = db.query(IncidentalChargeCategory).filter(IncidentalChargeCategory.id == category_id, IncidentalChargeCategory.is_deleted == False).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    
    if data.name is not None:
        dup = db.query(IncidentalChargeCategory).filter(
            IncidentalChargeCategory.name == data.name,
            IncidentalChargeCategory.id != category_id,
            IncidentalChargeCategory.is_deleted == False
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail="Ya existe otra categoría con ese nombre.")
        cat.name = data.name
        
    if data.description is not None:
        cat.description = data.description
    if data.icon is not None:
        cat.icon = data.icon
    if data.is_active is not None:
        cat.is_active = data.is_active
        
    db.commit()
    db.refresh(cat)
    log_action(db, user_id=current_user.id, resource="incidental_charge_categories", action="update",
               method="PUT", path=f"/admin/incidental-categories/{category_id}", status_code=200, request=request,
               metadata={"category_id": category_id})
    return cat

@router.delete("/incidental-categories/{category_id}", status_code=204, dependencies=[Depends(require_permission("incidentals", "delete"))])
def delete_admin_incidental_category(
    category_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Elimina lógicamente una categoría de cargo incidental."""
    cat = db.query(IncidentalChargeCategory).filter(IncidentalChargeCategory.id == category_id, IncidentalChargeCategory.is_deleted == False).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    
    cat.is_deleted = True
    db.commit()
    log_action(db, user_id=current_user.id, resource="incidental_charge_categories", action="delete",
               method="DELETE", path=f"/admin/incidental-categories/{category_id}", status_code=204, request=request,
               metadata={"category_id": category_id})

@router.get("/incidentals", response_model=list[IncidentalChargeRead], dependencies=[Depends(require_permission("incidentals", "read"))])
def get_all_incidental_charges(db: Session = Depends(get_db)):
    """Lista todos los cargos incidentales registrados en el sistema, ordenados por más recientes."""
    return db.query(IncidentalCharge).options(
        selectinload(IncidentalCharge.created_by),
        selectinload(IncidentalCharge.category),
        selectinload(IncidentalCharge.reservation)
    ).order_by(IncidentalCharge.created_at.desc()).all()

@router.get("/reservations/{res_id}/incidentals", response_model=list[IncidentalChargeRead], dependencies=[Depends(require_permission("incidentals", "read"))])
def get_reservation_incidental_charges(res_id: int, db: Session = Depends(get_db)):
    """Lista todos los cargos incidentales asociados a una reservación, cargando el staff que lo registró y la categoría."""
    return db.query(IncidentalCharge).options(
        selectinload(IncidentalCharge.created_by),
        selectinload(IncidentalCharge.category)
    ).filter(IncidentalCharge.reservation_id == res_id).order_by(IncidentalCharge.created_at.desc()).all()

@router.post("/reservations/{res_id}/incidentals", response_model=IncidentalChargeRead, status_code=201, dependencies=[Depends(require_permission("incidentals", "create"))])
def create_reservation_incidental_charge(
    res_id: int,
    data: IncidentalChargeCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Registra un nuevo cargo incidental a una reservación.
    Recalcula incidentals_total y envía una notificación.
    """
    reservation = db.query(Reservation).filter(Reservation.id == res_id, Reservation.is_deleted == False).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="No se pueden agregar cargos incidentales a una reservación cancelada")
        
    if data.category_id:
        category = db.query(IncidentalChargeCategory).filter(
            IncidentalChargeCategory.id == data.category_id,
            IncidentalChargeCategory.is_deleted == False
        ).first()
        if not category:
            raise HTTPException(status_code=400, detail="Categoría seleccionada no es válida o está inactiva")

    total_amount = data.amount * data.quantity

    new_charge = IncidentalCharge(
        reservation_id=res_id,
        category_id=data.category_id,
        description=data.description,
        amount=data.amount,
        quantity=data.quantity,
        total_amount=total_amount,
        apply_tax=data.apply_tax,
        payment_status="pending",
        notes=data.notes,
        created_by_user_id=current_user.id
    )
    
    db.add(new_charge)
    db.flush() # Para obtener el ID del cargo incidental
    
    # Recalculamos
    recalculate_reservation_incidentals_total(reservation, db)
    db.commit()
    db.refresh(new_charge)
    
    # Notificación in-app
    try:
        from app.services.notification_service import notify_incidental_charge_created
        notify_incidental_charge_created(db, reservation, new_charge)
    except Exception as e:
        print(f"Error al enviar notificación de cargo incidental: {e}")
        
    log_action(db, user_id=current_user.id, resource="incidental_charges", action="create",
               method="POST", path=f"/admin/reservations/{res_id}/incidentals", status_code=201, request=request,
               metadata={"reservation_id": res_id, "charge_id": new_charge.id, "total_amount": float(total_amount)})
               
    return new_charge

@router.put("/incidentals/{charge_id}", response_model=IncidentalChargeRead, dependencies=[Depends(require_permission("incidentals", "update"))])
def update_reservation_incidental_charge(
    charge_id: int,
    data: IncidentalChargeUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualiza los datos de un cargo incidental. Solo se permite si el cargo está en estado 'pending'.
    Recalcula el total de la reservación.
    """
    charge = db.query(IncidentalCharge).filter(IncidentalCharge.id == charge_id).first()
    if not charge:
        raise HTTPException(status_code=404, detail="Cargo incidental no encontrado")
        
    if charge.payment_status != "pending":
        raise HTTPException(status_code=400, detail="Solo se pueden editar cargos incidentales que estén pendientes de pago")
        
    reservation = db.query(Reservation).filter(Reservation.id == charge.reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    if data.category_id is not None:
        category = db.query(IncidentalChargeCategory).filter(
            IncidentalChargeCategory.id == data.category_id,
            IncidentalChargeCategory.is_deleted == False
        ).first()
        if not category:
            raise HTTPException(status_code=400, detail="Categoría seleccionada no es válida o está inactiva")
        charge.category_id = data.category_id
        
    if data.description is not None:
        charge.description = data.description
        
    if data.amount is not None:
        charge.amount = data.amount
        
    if data.quantity is not None:
        charge.quantity = data.quantity
        
    if data.apply_tax is not None:
        charge.apply_tax = data.apply_tax
        
    if data.notes is not None:
        charge.notes = data.notes
        
    # Recalculamos total del cargo
    charge.total_amount = charge.amount * charge.quantity
    db.flush()
    
    # Recalculamos total de la reservación
    recalculate_reservation_incidentals_total(reservation, db)
    db.commit()
    db.refresh(charge)
    
    log_action(db, user_id=current_user.id, resource="incidental_charges", action="update",
               method="PUT", path=f"/admin/incidentals/{charge_id}", status_code=200, request=request,
               metadata={"charge_id": charge_id, "reservation_id": reservation.id})
               
    return charge

@router.post("/incidentals/{charge_id}/waive", response_model=IncidentalChargeRead, dependencies=[Depends(require_permission("incidentals", "update"))])
def waive_reservation_incidental_charge(
    charge_id: int,
    data: IncidentalChargeWaive,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Condonar un cargo incidental (cortesía o error de registro). El estado cambia a 'waived'.
    Se requiere un motivo obligatorio. Recalcula el total de la reservación (los waived no suman) y notifica.
    """
    charge = db.query(IncidentalCharge).filter(IncidentalCharge.id == charge_id).first()
    if not charge:
        raise HTTPException(status_code=404, detail="Cargo incidental no encontrado")
        
    if charge.payment_status != "pending":
        raise HTTPException(status_code=400, detail="Solo se pueden condonar cargos incidentales que estén pendientes de pago")
        
    reservation = db.query(Reservation).filter(Reservation.id == charge.reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    charge.payment_status = "waived"
    charge.waived_reason = data.reason
    db.flush()
    
    # Recalculamos total de la reservación
    recalculate_reservation_incidentals_total(reservation, db)
    db.commit()
    db.refresh(charge)
    
    # Notificación in-app
    try:
        from app.services.notification_service import notify_incidental_charge_waived
        notify_incidental_charge_waived(db, reservation, charge)
    except Exception as e:
        print(f"Error al enviar notificación de cargo condonado: {e}")
        
    log_action(db, user_id=current_user.id, resource="incidental_charges", action="waive",
               method="POST", path=f"/admin/incidentals/{charge_id}/waive", status_code=200, request=request,
               metadata={"charge_id": charge_id, "reservation_id": reservation.id, "reason": data.reason})
               
    return charge

@router.delete("/incidentals/{charge_id}", status_code=204, dependencies=[Depends(require_permission("incidentals", "delete"))])
def delete_reservation_incidental_charge(
    charge_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Elimina físicamente un cargo incidental de la base de datos si y solo si está en estado 'pending'.
    Recalcula el total de la reservación.
    """
    charge = db.query(IncidentalCharge).filter(IncidentalCharge.id == charge_id).first()
    if not charge:
        raise HTTPException(status_code=404, detail="Cargo incidental no encontrado")
        
    if charge.payment_status != "pending":
        raise HTTPException(status_code=400, detail="Solo se pueden eliminar cargos incidentales que estén pendientes de pago")
        
    reservation = db.query(Reservation).filter(Reservation.id == charge.reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    db.delete(charge)
    db.flush()
    
    # Recalculamos total de la reservación
    recalculate_reservation_incidentals_total(reservation, db)
    db.commit()
    
    log_action(db, user_id=current_user.id, resource="incidental_charges", action="delete",
               method="DELETE", path=f"/admin/incidentals/{charge_id}", status_code=204, request=request,
               metadata={"charge_id": charge_id, "reservation_id": reservation.id})

@router.post("/incidentals/{charge_id}/evidence", response_model=IncidentalChargeRead, dependencies=[Depends(require_permission("incidentals", "update"))])
def upload_incidental_evidence(
    charge_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sube una foto/evidencia del daño a Cloudinary y la asocia al cargo incidental."""
    charge = db.query(IncidentalCharge).filter(IncidentalCharge.id == charge_id).first()
    if not charge:
        raise HTTPException(status_code=404, detail="Cargo incidental no encontrado")
        
    if charge.payment_status != "pending":
        raise HTTPException(status_code=400, detail="Solo se puede subir evidencia para cargos incidentales pendientes de pago")
        
    # Subir imagen a Cloudinary usando la función utilitaria
    evidence_url = upload_image_to_cloudinary(file)
    charge.evidence_url = evidence_url
    db.commit()
    db.refresh(charge)
    
    return charge

