import random
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validar que la reservación exista, no esté borrada y le pertenezca
    reservation = db.query(Reservation).options(selectinload(Reservation.room)).filter(
        Reservation.id == data.reservation_id,
        Reservation.is_deleted == False
    ).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada o ha sido eliminada")
        
    if reservation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación")
        
    if reservation.status != "pending":
        raise HTTPException(status_code=400, detail="Esta reservación ya ha sido pagada o cancelada")

    # Validación adicional de método de pago (Transferencias usan el nuevo endpoint)
    valid_methods = ["cash", "card"]
    if data.method.lower() not in valid_methods:
        raise HTTPException(status_code=400, detail=f"Método de pago no válido para este endpoint. Opciones: {', '.join(valid_methods)}")

    # Double check in payments table to avoid IntegrityError (unique constraint)
    existing_payment = db.query(Payment).filter(
        Payment.reservation_id == data.reservation_id,
        Payment.status.in_(["completed", "verifying", "pending"])
    ).first()
    if existing_payment:
        raise HTTPException(status_code=400, detail="Ya existe un pago en proceso o completado para esta reservación")
        
    if data.amount < reservation.total_cost:
        raise HTTPException(status_code=400, detail="El monto del pago es menor al total de la reservación")



    # Generar receipt data
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
        "method": data.method
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
    
    # Update reservation status
    reservation.status = "verifying" if data.method.lower() == "cash" else "confirmed"
    
    db.commit()
    db.refresh(payment)
    
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
    reservation = db.query(Reservation).options(selectinload(Reservation.room)).filter(
        Reservation.id == reservation_id,
        Reservation.is_deleted == False
    ).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada o ha sido eliminada")
        
    if reservation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación")
        
    if reservation.status != "pending":
        raise HTTPException(status_code=400, detail="Esta reservación ya ha sido pagada o cancelada")

    existing_payment = db.query(Payment).filter(
        Payment.reservation_id == reservation_id,
        Payment.status.in_(["completed", "verifying", "pending"])
    ).first()
    if existing_payment:
        raise HTTPException(status_code=400, detail="Ya existe un pago en proceso o completado para esta reservación")

    if amount < float(reservation.total_cost):
        raise HTTPException(status_code=400, detail="El monto del pago es menor al total de la reservación")

    # Subir imagen a Cloudinary
    try:
        receipt_url = upload_image_to_cloudinary(file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir el comprobante: {str(e)}")

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
        "method": "transfer"
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
    reservation = db.query(Reservation).filter(
        Reservation.id == reservation_id,
        Reservation.user_id == current_user.id,
        Reservation.is_deleted == False
    ).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
    if reservation.status != "pending":
        raise HTTPException(status_code=400, detail="La reservación no está pendiente de pago")
        
    url = await generate_wompi_payment_link(reservation.unique_id, float(reservation.total_cost), redirect_url)
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
