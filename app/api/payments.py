import random
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.reservation import Reservation
from app.models.payment import Payment
from app.schemas.payment import PaymentCreate, PaymentRead

router = APIRouter(prefix="/payments", tags=["Payments"])

@router.post("/", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
def process_payment(
    data: PaymentCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validar que la reservación exista, no esté borrada y le pertenezca
    # Incluimos las amenidades extras e incidentales para poder calcular el total y agregarlas al recibo
    from app.models.extra_amenity import ReservationExtraAmenity
    from app.models.incidental_charge import IncidentalCharge
    reservation = db.query(Reservation).options(
        selectinload(Reservation.room),
        selectinload(Reservation.extras).selectinload(ReservationExtraAmenity.extra_amenity),
        selectinload(Reservation.incidental_charges)
    ).filter(
        Reservation.id == data.reservation_id,
        Reservation.is_deleted == False
    ).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada o ha sido eliminada")
        
    if reservation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación")
        
    from decimal import Decimal
    from app.services.reservation_service import calculate_grand_total
    total_paid = sum((p.amount for p in reservation.payments if p.status == "completed"), Decimal("0.0"))
    grand_total = calculate_grand_total(reservation, db)
    balance = round(grand_total - total_paid, 2)

    if reservation.status not in ["pending", "confirmed"]:
        raise HTTPException(status_code=400, detail="Esta reservación no está en un estado que permita pagos")
    if reservation.status == "confirmed" and balance <= 0:
        raise HTTPException(status_code=400, detail="Esta reservación ya está completamente pagada")

    # Validación adicional de método de pago (Transferencias usan el nuevo endpoint)
    valid_methods = ["cash", "card"]
    if data.method.lower() not in valid_methods:
        raise HTTPException(status_code=400, detail=f"Método de pago no válido para este endpoint. Opciones: {', '.join(valid_methods)}")

    # Double check in payments table to avoid duplicate payment in progress
    in_progress_payment = db.query(Payment).filter(
        Payment.reservation_id == data.reservation_id,
        Payment.status.in_(["verifying", "pending"])
    ).first()
    if in_progress_payment:
        raise HTTPException(status_code=400, detail="Ya existe un pago en proceso de verificación para esta reservación")

    # Tolerancia de 1 centavo para evitar errores de precisión float
    amount_decimal = Decimal(str(data.amount)).quantize(Decimal("0.01"))
    if amount_decimal < (balance - Decimal("0.01")):
        raise HTTPException(status_code=400, detail=f"El monto del pago es menor al saldo pendiente (${float(balance):.2f})")


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

    profile = current_user.profile
    receipt_data = {
        "company": "Hotel AFE",
        "date": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "customer": f"{profile.first_name} {profile.last_name}" if profile else current_user.email,
        "customer_email": current_user.email,
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

    payment_status = "verifying" if data.method.lower() == "cash" else "completed"

    payment = Payment(
        reservation_id=data.reservation_id,
        amount=data.amount,
        method=data.method,
        status=payment_status,
        receipt_type=data.receipt_type,
        receipt_data=receipt_data
    )
    db.add(payment)

    # Capturar estado previo antes de modificar
    was_confirmed = reservation.status == "confirmed"

    # Update reservation status
    reservation.status = "verifying" if data.method.lower() == "cash" else "confirmed"

    db.commit()
    db.refresh(payment)

    # Solo enviar email si el pago se completó de inmediato (tarjeta)
    # Los pagos en efectivo/transferencia quedan en 'verifying'; el email se envía al aprobar
    if payment.status == "completed" and reservation.user and reservation.user.email:
        from app.core.mail import send_payment_receipt_email, send_reservation_confirmed_email
        from app.services.pdf_service import generate_receipt_pdf
        from app.services.dte_json_service import generate_dte_json
        from app.utils.date_utils import format_payment_datetime

        profile = current_user.profile
        first_name = profile.first_name if profile else "Cliente"
        payment_date_fmt = format_payment_datetime()

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
            email=current_user.email,
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
                email=current_user.email,
                first_name=first_name,
                reservation_id=reservation.unique_id,
                check_in=reservation.check_in.strftime("%d/%m/%Y"),
                check_out=reservation.check_out.strftime("%d/%m/%Y"),
                pdf_content=pdf_content,
                json_content=json_content
            )

    return payment

from fastapi import UploadFile, File, Form
from app.services.room_service import upload_image_to_cloudinary

@router.post("/transfer", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def process_transfer_payment(
    reservation_id: int = Form(...),
    amount: float = Form(...),
    receipt_type: str = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from app.models.extra_amenity import ReservationExtraAmenity
    from app.models.incidental_charge import IncidentalCharge
    reservation = db.query(Reservation).options(
        selectinload(Reservation.room),
        selectinload(Reservation.extras).selectinload(ReservationExtraAmenity.extra_amenity),
        selectinload(Reservation.incidental_charges)
    ).filter(
        Reservation.id == reservation_id,
        Reservation.is_deleted == False
    ).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada o ha sido eliminada")
        
    if reservation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación")
        
    from decimal import Decimal
    from app.services.reservation_service import calculate_grand_total
    total_paid = sum((p.amount for p in reservation.payments if p.status == "completed"), Decimal("0.0"))
    grand_total = calculate_grand_total(reservation, db)
    balance = round(grand_total - total_paid, 2)

    if reservation.status not in ["pending", "confirmed"]:
        raise HTTPException(status_code=400, detail="Esta reservación no está en un estado que permita pagos")
    if reservation.status == "confirmed" and balance <= 0:
        raise HTTPException(status_code=400, detail="Esta reservación ya está completamente pagada")

    # Double check in payments table to avoid duplicate payment in progress
    in_progress_payment = db.query(Payment).filter(
        Payment.reservation_id == reservation_id,
        Payment.status.in_(["verifying", "pending"])
    ).first()
    if in_progress_payment:
        raise HTTPException(status_code=400, detail="Ya existe un pago en proceso de verificación para esta reservación")

    # Tolerancia de 1 centavo para evitar errores de precisión float
    amount_decimal = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount_decimal < (balance - Decimal("0.01")):
        raise HTTPException(status_code=400, detail=f"El monto del pago es menor al saldo pendiente (${float(balance):.2f})")

    # Subir imagen a Cloudinary
    try:
        receipt_url = upload_image_to_cloudinary(file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir el comprobante: {str(e)}")

    # Generar receipt data de forma itemizada y dinámica
    from app.services.system_settings_service import get_tax_iva, get_tax_tourism
    from app.services.payment_allocation_service import allocate_payment_items
    
    iva_rate = float(get_tax_iva(db))
    tourism_rate = float(get_tax_tourism(db))
    allocated_items = allocate_payment_items(db, reservation, Decimal(str(amount)))
    
    room_base = sum(item["total_amount"] for item in allocated_items if item["type"] == "room")
    room_iva = sum(item["tax"] for item in allocated_items if item["type"] == "room")
    room_tourism = sum(item["tourism"] for item in allocated_items if item["type"] == "room")
    
    extras_base = sum(item["total_amount"] for item in allocated_items if item["type"] == "extra")
    extras_iva = sum(item["tax"] for item in allocated_items if item["type"] == "extra")
    
    incidentals_base = sum(item["total_amount"] for item in allocated_items if item["type"] == "incidental")
    incidentals_iva = sum(item["tax"] for item in allocated_items if item["type"] == "incidental")

    profile = current_user.profile
    receipt_data = {
        "company": "Hotel AFE",
        "date": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "customer": f"{profile.first_name} {profile.last_name}" if profile else current_user.email,
        "customer_email": current_user.email,
        "receipt_type": receipt_type,
        "reservation_id": reservation.unique_id,
        "room_number": reservation.room.number,
        "room_type": reservation.room.type,
        "check_in": reservation.check_in.isoformat(),
        "check_out": reservation.check_out.isoformat(),
        "amount_paid": str(amount),
        "method": "transfer",
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

    if receipt_type == "fiscal_credit" and profile:
        receipt_data.update({
            "nit": profile.nit,
            "nrc": profile.nrc,
            "business_name": profile.business_name or f"{profile.first_name} {profile.last_name}",
            "economic_activity": profile.economic_activity
        })

    payment = Payment(
        reservation_id=reservation_id,
        amount=amount,
        method="transfer",
        status="verifying",
        receipt_type=receipt_type,
        receipt_url=receipt_url,
        receipt_data=receipt_data
    )
    db.add(payment)
    
    # Update reservation status
    reservation.status = "verifying"
    
    db.commit()
    db.refresh(payment)
    
    return payment

from app.services.wompi_service import generate_wompi_payment_link

@router.post("/{reservation_id}/wompi-link", status_code=200)
async def create_wompi_link_user(
    reservation_id: int,
    request: Request,
    redirect_url: str = "http://localhost:5173/profile/reservations",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify the reservation belongs to the user
    reservation = db.query(Reservation).options(
        selectinload(Reservation.incidental_charges)
    ).filter(
        Reservation.id == reservation_id,
        Reservation.user_id == current_user.id,
        Reservation.is_deleted == False
    ).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    from decimal import Decimal
    from app.services.reservation_service import calculate_grand_total
    total_paid = sum((p.amount for p in reservation.payments if p.status == "completed"), Decimal("0.0"))
    grand_total = calculate_grand_total(reservation, db)
    balance = round(grand_total - total_paid, 2)

    if reservation.status not in ["pending", "confirmed"]:
        raise HTTPException(status_code=400, detail="Esta reservación no está en un estado que permita pagos")
    if reservation.status == "confirmed" and balance <= 0:
        raise HTTPException(status_code=400, detail="Esta reservación ya está completamente pagada")

    url = await generate_wompi_payment_link(reservation.unique_id, float(balance), redirect_url)
    return {"url": url}

@router.get("/{payment_id}", response_model=PaymentRead)
def get_payment(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    payment = db.query(Payment).options(selectinload(Payment.reservation)).filter(Payment.id == payment_id).first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
        
    if payment.reservation.user_id != current_user.id:
        roles = [r.name for r in current_user.roles]
        if "admin" not in roles and "manager" not in roles:
            raise HTTPException(status_code=403, detail="No autorizado")

    return payment

@router.delete("/{payment_id}", response_model=PaymentRead)
def cancel_verifying_payment(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    payment = db.query(Payment).options(selectinload(Payment.reservation)).filter(Payment.id == payment_id).first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
        
    if payment.reservation.user_id != current_user.id:
        roles = [r.name for r in current_user.roles]
        if "admin" not in roles and "manager" not in roles:
            raise HTTPException(status_code=403, detail="No autorizado")

    if payment.status != "verifying":
        raise HTTPException(status_code=400, detail="Solo se pueden cancelar pagos que están en proceso de verificación")

    payment.status = "failed"
    
    if payment.reservation.status == "verifying":
        payment.reservation.status = "pending"

    db.commit()
    db.refresh(payment)
    return payment
