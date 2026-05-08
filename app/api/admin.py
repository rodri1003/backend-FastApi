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
    send_refund_processed_email
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
from app.schemas.user import UserRead, UserCreateAdmin, UserUpdateAdmin, RoleRead, RoleCreate, RoleUpdate
from app.schemas.reservation import ReservationRead, AdminReservationCreate, AdminReservationUpdate
from app.schemas.payment import PaymentCreate, PaymentRead
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
    occupied_room_ids = db.query(Reservation.room_id).filter(
        Reservation.check_in <= today,
        Reservation.check_out > today,
        Reservation.status == "confirmed",
        Reservation.is_deleted == False
    ).all()
    occupied_now = len(set(r[0] for r in occupied_room_ids))
    
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
    forecast_raw = db.query(
        Reservation.check_in.label("day"),
        func.sum(Reservation.total_cost).label("total")
    ).filter(
        Reservation.status.in_(["pending", "confirmed"]),
        Reservation.check_in >= today,
        Reservation.check_in <= next_week,
        Reservation.is_deleted == False
    ).group_by(Reservation.check_in).all()
    
    forecast_map = {str(row.day): float(row.total) for row in forecast_raw}

    full_trend = []
    # Combine Historical
    for i in range(29, -1, -1):
        d = (today - timedelta(days=i))
        d_str = d.isoformat()
        full_trend.append({"date": d_str, "amount": revenue_map.get(d_str, 0.0), "type": "actual"})
    
    # Add Forecast
    for i in range(1, 8):
        d = (today + timedelta(days=i))
        d_str = d.isoformat()
        full_trend.append({"date": d_str, "amount": forecast_map.get(d_str, 0.0), "type": "forecast"})

    # 6. Market Mix (Revenue by Room Type)
    market_mix = db.query(
        RoomType.name,
        func.sum(Payment.amount).label("total")
    ).join(Room, Room.room_type_id == RoomType.id)\
     .join(Reservation, Reservation.room_id == Room.id)\
     .join(Payment, Payment.reservation_id == Reservation.id)\
     .filter(Payment.status == "completed", Payment.created_at >= thirty_days_ago)\
     .group_by(RoomType.name).all()
    
    mix_data = [{"label": row.name, "value": float(row.total)} for row in market_mix]

    return {
        "kpis": {
            "revenue": {
                "total": float(rev_total), 
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

@router.get("/reservations", response_model=list[ReservationRead], dependencies=[Depends(require_permission("reservations", "read"))])
def list_all_reservations(
    db: Session = Depends(get_db),
    room_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(Reservation).options(selectinload(Reservation.room)).filter(Reservation.is_deleted == False)
    
    if room_id:
        query = query.filter(Reservation.room_id == room_id)
        
    reservations = (
        query.order_by(Reservation.created_at.desc())
        .offset(offset)
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

    reservation = db.query(Reservation).options(selectinload(Reservation.room), selectinload(Reservation.user)).filter(
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
    total_cost = Decimal(str(reservation.total_cost))
    balance = total_cost - total_paid

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
        "method": data.method
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
    
    # Auto-update status if fully paid
    if total_paid + Decimal(str(data.amount)) >= Decimal(str(reservation.total_cost)):
        reservation.status = "confirmed"
    
    db.commit()
    db.refresh(payment)

    if reservation.status == "confirmed" and reservation.user and reservation.user.email:
        first_name = reservation.user.profile.first_name if reservation.user.profile else "Cliente"
        
        # Generar PDF del DTE
        try:
            pdf_content = generate_receipt_pdf(payment.receipt_data)
        except Exception as e:
            print(f"Error generando PDF para reserva {reservation.unique_id}: {str(e)}")
            pdf_content = None

        # Generar JSON del DTE
        try:
            json_content = generate_dte_json(payment.receipt_data)
        except Exception as e:
            print(f"Error generando JSON DTE para reserva {reservation.unique_id}: {str(e)}")
            json_content = None

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
    total_cost = Decimal(str(reservation.total_cost))
    balance = total_cost - total_paid

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
    if reservation.status != "pending":
        raise HTTPException(status_code=400, detail="La reservación no está pendiente de pago")
        
    from sqlalchemy import func
    from app.models.payment import Payment
    from decimal import Decimal
    raw_total_paid = db.query(func.sum(Payment.amount)).filter(
        Payment.reservation_id == res_id, 
        Payment.status == "completed"
    ).scalar() or 0.0
    
    total_paid = Decimal(str(raw_total_paid))
    balance = Decimal(str(reservation.total_cost)) - total_paid
    
    if balance <= 0:
        raise HTTPException(status_code=400, detail="Esta reservación ya está pagada")

    url = await generate_wompi_payment_link(reservation.unique_id, float(balance), redirect_url)
    return {"url": url}

@router.get("/payments", response_model=list[PaymentRead], dependencies=[Depends(require_permission("payments", "read"))])
def list_all_payments(
    db: Session = Depends(get_db),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    method: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(Payment).options(
        selectinload(Payment.reservation).selectinload(Reservation.user),
        selectinload(Payment.reservation).selectinload(Reservation.room)
    )
    
    if start_date:
        query = query.filter(Payment.created_at >= start_date)
    if end_date:
        query = query.filter(Payment.created_at <= end_date)
    if method:
        query = query.filter(Payment.method == method)
    if status:
        query = query.filter(Payment.status == status)
        
    payments = query.order_by(Payment.created_at.desc()).offset(offset).limit(limit).all()
    return payments

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

    payment = db.query(Payment).options(
        selectinload(Payment.reservation).selectinload(Reservation.user).selectinload(User.profile),
        selectinload(Payment.reservation).selectinload(Reservation.room)
    ).filter(Payment.id == payment_id).first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
        
    if payment.status != "verifying":
        raise HTTPException(status_code=400, detail="El pago no está en estado de verificación")

    reservation = payment.reservation

    if data.action == "approve":
        payment.status = "completed"
        
        # Check if full amount is met
        from sqlalchemy import func
        from decimal import Decimal
        raw_total_paid = db.query(func.sum(Payment.amount)).filter(
            Payment.reservation_id == reservation.id, 
            Payment.status == "completed"
        ).scalar() or 0.0
        
        total_paid = Decimal(str(raw_total_paid)) + Decimal(str(payment.amount))
        
        if total_paid >= Decimal(str(reservation.total_cost)):
            reservation.status = "confirmed"
            
            # Notificar al cliente
            if reservation.user and reservation.user.email:
                first_name = reservation.user.profile.first_name if reservation.user.profile else "Cliente"
                
                # Generar PDF del DTE
                try:
                    pdf_content = generate_receipt_pdf(payment.receipt_data)
                except Exception as e:
                    print(f"Error generando PDF para reserva {reservation.unique_id}: {str(e)}")
                    pdf_content = None

                # Generar JSON del DTE
                try:
                    json_content = generate_dte_json(payment.receipt_data)
                except Exception as e:
                    print(f"Error generando JSON DTE para reserva {reservation.unique_id}: {str(e)}")
                    json_content = None

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
    Reenvía el correo de confirmación de una reservación, incluyendo el DTE.
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

    return {"message": "Correo de confirmación encolado para reenvío"}


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
    limit: int = Query(default=100, ge=1, le=500),
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
    limit: int = Query(default=100, ge=1, le=500),
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
