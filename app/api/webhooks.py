from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.reservation import Reservation
from app.models.payment import Payment
from datetime import datetime
import json
import logging

import hmac
import hashlib
from app.core.config import settings
from app.core.logging_utils import mask_pii

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

@router.post("/wompi", status_code=status.HTTP_200_OK)
async def wompi_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Recibe las notificaciones asíncronas de Wompi El Salvador.
    """
    # 1. Validar Hash de Seguridad (HMAC-SHA256)
    wompi_hash = request.headers.get("wompi_hash")
    if not wompi_hash:
        logger.error("Wompi Webhook received without 'wompi_hash' header")
        raise HTTPException(status_code=401, detail="Missing signature")

    body_bytes = await request.body()
    
    # Calcular HMAC con el API Secret del comercio
    expected_hash = hmac.new(
        key=settings.WOMPI_API_SECRET.encode("utf-8"),
        msg=body_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(wompi_hash, expected_hash):
        logger.error(f"Invalid Webhook Signature. Expected: {expected_hash}, Received: {wompi_hash}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
        # Enmascarar info sensible antes de loggear
        masked_payload = mask_pii(payload)
        logger.info(f"Received Valid Wompi Webhook: {json.dumps(masked_payload)}")
    except Exception as e:
        logger.error(f"Error parsing Wompi webhook: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Procesamiento adaptado para la API de Wompi El Salvador (Banco Agrícola)
    # Wompi SV no usa envoltorio 'event' ni 'data', envía el objeto plano
    
    # 1. Intentamos leer el formato Wompi Colombia por si acaso
    event_type = payload.get("event")
    data = payload.get("data", {})
    transaction = data.get("transaction", {})
    
    # 2. Extraer valores basados en Wompi SV prioritariamente, o caer en Wompi CO
    tx_status = payload.get("ResultadoTransaccion") or transaction.get("status") or payload.get("status")
    
    # El ID único que enviamos como referencia puede venir en 'IdExterno' o en 'EnlacePago.IdentificadorEnlaceComercio'
    enlace_pago = payload.get("EnlacePago", {})
    reference = payload.get("IdExterno") or enlace_pago.get("IdentificadorEnlaceComercio") or transaction.get("reference") or payload.get("reference")
    
    # El monto
    monto_sv = payload.get("Monto")
    if monto_sv:
        amount = float(monto_sv)
    else:
        amount = transaction.get("amount_in_cents", 0) / 100 if transaction.get("amount_in_cents") else payload.get("amount", 0)
        
    payment_method = payload.get("FormaPagoUtilizada") or transaction.get("payment_method_type") or payload.get("payment_method", "card")
    gateway_id = payload.get("IdTransaccion") or transaction.get("id") or payload.get("id", "wompi_txn")

    if not reference:
        logger.warning("Wompi Webhook missing reference ID")
        return {"status": "ignored"}
        
    # Wompi SV retorna "ExitosaAprobada"
    if tx_status in ["ExitosaAprobada", "APPROVED", "COMPLETED", "EXITOSO"]:
        # Buscar la reservación previniendo errores de casteo a entero si es un string (e.g UUID)
        query = db.query(Reservation).filter(Reservation.unique_id == str(reference))
        if str(reference).isdigit():
            query = db.query(Reservation).filter(
                (Reservation.unique_id == str(reference)) | (Reservation.id == int(reference))
            )
        res = query.first()

        if not res:
            logger.error(f"Reservation {reference} not found for payment webhook")
            raise HTTPException(status_code=404, detail="Reservation not found")

        # Verificar idempotencia
        existing_payments = db.query(Payment).filter(Payment.reservation_id == res.id).all()
        
        def get_gw_ref(p):
            if not p.receipt_data: return None
            if isinstance(p.receipt_data, dict): return p.receipt_data.get("gateway_ref")
            if isinstance(p.receipt_data, str):
                try: return json.loads(p.receipt_data).get("gateway_ref")
                except: return None
            return None

        already_processed = any(get_gw_ref(p) == gateway_id for p in existing_payments)
        
        if already_processed:
            logger.info(f"Payment {gateway_id} already processed for reservation {res.id}")
            return {"status": "already_processed"}

        actual_paid = amount if amount > 0 else res.total_cost

        # Generar comprobante
        receipt_data = {
            "company": "Hotel AFE",
            "date": datetime.now().isoformat(),
            "customer": res.user.email if getattr(res, "user", None) else "Online Gateway",
            "receipt_type": "Consumidor Final",
            "reservation_id": res.unique_id,
            "room_number": getattr(res.room, "number", "N/A") if res.room else "N/A",
            "room_type": getattr(res.room, "type", "N/A") if res.room else "N/A",
            "check_in": res.check_in.isoformat() if res.check_in else "",
            "check_out": res.check_out.isoformat() if res.check_out else "",
            "amount_paid": str(actual_paid),
            "method": payment_method.lower(),
            "gateway_ref": gateway_id
        }

        # Grabar el pago real
        new_payment = Payment(
            reservation_id=res.id,
            amount=actual_paid,
            method="card",
            status="completed",
            receipt_type="Consumidor Final",
            receipt_data=receipt_data
        )
        db.add(new_payment)
        
        from decimal import Decimal
        total_paid_before = sum([Decimal(str(p.amount)) for p in existing_payments if p.status == "completed"], Decimal("0.0"))
        if total_paid_before + Decimal(str(actual_paid)) >= Decimal(str(res.total_cost)):
            res.status = "confirmed"
            
        db.commit()
        logger.info(f"Successfully processed Wompi payment for reservation {res.id}")

    return {"status": "received"}
