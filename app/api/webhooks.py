from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.reservation import Reservation
from app.models.payment import Payment
from datetime import datetime, timezone
import json
import logging

import hmac
import hashlib
from app.core.config import settings
from app.core.logging_utils import mask_pii
from fastapi import BackgroundTasks
from app.core.mail import send_reservation_confirmed_email, send_payment_receipt_email
from app.services.pdf_service import generate_receipt_pdf
from app.services.dte_json_service import generate_dte_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

@router.post("/wompi", status_code=status.HTTP_200_OK)
async def wompi_webhook(
    request: Request, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
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
        from sqlalchemy.orm import selectinload
        from app.models.extra_amenity import ReservationExtraAmenity
        from app.models.incidental_charge import IncidentalCharge
        # Buscar la reservación previniendo errores de casteo a entero si es un string (e.g UUID)
        query = db.query(Reservation).options(
            selectinload(Reservation.room),
            selectinload(Reservation.extras).selectinload(ReservationExtraAmenity.extra_amenity),
            selectinload(Reservation.incidental_charges)
        ).filter(Reservation.unique_id == str(reference))
        if str(reference).isdigit():
            query = db.query(Reservation).options(
                selectinload(Reservation.room),
                selectinload(Reservation.extras).selectinload(ReservationExtraAmenity.extra_amenity),
                selectinload(Reservation.incidental_charges)
            ).filter(
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

        extras_base = float(res.extras_total)
        extras_iva = extras_base * 0.13
        
        from decimal import Decimal as Dec2
        from app.services.reservation_service import calculate_grand_total
        grand_total = float(calculate_grand_total(res, db))

        actual_paid = amount if amount > 0 else grand_total

        # Construir dirección completa y obtener datos del perfil
        profile = res.user.profile if (res.user and res.user.profile) else None
        address_parts = []
        if profile:
            if profile.address_complement: address_parts.append(profile.address_complement)
            if profile.municipality: address_parts.append(profile.municipality)
            if profile.department: address_parts.append(profile.department)
            if profile.country: address_parts.append(profile.country)
        
        full_address = ", ".join(address_parts) if address_parts else "EL SALVADOR"

        # Generar comprobante de forma itemizada y dinámica
        from app.services.system_settings_service import get_tax_iva, get_tax_tourism
        from app.services.payment_allocation_service import allocate_payment_items
        from decimal import Decimal
        
        iva_rate = float(get_tax_iva(db))
        tourism_rate = float(get_tax_tourism(db))
        allocated_items = allocate_payment_items(db, res, Decimal(str(actual_paid)))
        
        room_base = sum(item["total_amount"] for item in allocated_items if item["type"] == "room")
        room_iva = sum(item["tax"] for item in allocated_items if item["type"] == "room")
        room_tourism = sum(item["tourism"] for item in allocated_items if item["type"] == "room")
        
        extras_base_alloc = sum(item["total_amount"] for item in allocated_items if item["type"] == "extra")
        extras_iva_alloc = sum(item["tax"] for item in allocated_items if item["type"] == "extra")
        
        incidentals_base_alloc = sum(item["total_amount"] for item in allocated_items if item["type"] == "incidental")
        incidentals_iva_alloc = sum(item["tax"] for item in allocated_items if item["type"] == "incidental")

        receipt_data = {
            "company": "Hotel AFE",
            "date": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "customer": f"{profile.first_name} {profile.last_name}" if profile else (res.user.email if res.user else "Online Gateway"),
            "customer_email": res.user.email if res.user else None,
            "customer_address": full_address,
            "customer_phone": profile.phone if profile else "---",
            "document_number": profile.document_number if profile else "---",
            "receipt_type": "Consumidor Final",
            "reservation_id": res.unique_id,
            "room_number": getattr(res.room, "number", "N/A") if res.room else "N/A",
            "room_type": getattr(res.room, "type", "N/A") if res.room else "N/A",
            "check_in": res.check_in.isoformat() if res.check_in else "",
            "check_out": res.check_out.isoformat() if res.check_out else "",
            "amount_paid": str(actual_paid),
            "method": payment_method.lower(),
            "gateway_ref": gateway_id,
            "tax_iva_rate": iva_rate,
            "tax_tourism_rate": tourism_rate,
            "room_base": float(room_base),
            "room_iva": float(room_iva),
            "room_tourism": float(room_tourism),
            "extras_base": float(extras_base_alloc),
            "extras_iva": float(extras_iva_alloc),
            "incidentals_base": float(incidentals_base_alloc),
            "incidentals_iva": float(incidentals_iva_alloc),
            "items": allocated_items,
            "extras": [ex for ex in allocated_items if ex["type"] == "extra"],
            "incidentals": [inc for inc in allocated_items if inc["type"] == "incidental"]
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

        # Capturar estado previo antes de modificar
        was_confirmed = res.status == "confirmed"

        from decimal import Decimal
        total_paid_before = sum([Decimal(str(p.amount)) for p in existing_payments if p.status == "completed"], Decimal("0.0"))
        if total_paid_before + Decimal(str(actual_paid)) >= Decimal(str(round(grand_total, 2))):
            res.status = "confirmed"
            for extra in res.extras:
                if extra.payment_status == "pending":
                    extra.payment_status = "paid"
            for inc in res.incidental_charges:
                if inc.payment_status == "pending":
                    inc.payment_status = "paid"

        db.commit()
        logger.info(f"Successfully processed Wompi payment for reservation {res.id}")

        # Notificar al cliente tras éxito en Wompi
        if res.user and res.user.email:
            from app.utils.date_utils import format_payment_datetime
            first_name = res.user.profile.first_name if (res.user.profile and res.user.profile.first_name) else "Cliente"
            payment_date_fmt = format_payment_datetime()

            # Generar PDF del DTE
            try:
                pdf_content = generate_receipt_pdf(receipt_data)
            except Exception as e:
                logger.error(f"Error generando PDF para reserva {res.unique_id} desde Webhook: {str(e)}")
                pdf_content = None

            # Generar JSON del DTE
            try:
                json_content = generate_dte_json(receipt_data)
            except Exception as e:
                logger.error(f"Error generando JSON DTE para reserva {res.unique_id} desde Webhook: {str(e)}")
                json_content = None

            # SIEMPRE: enviar comprobante de pago con DTE
            background_tasks.add_task(
                send_payment_receipt_email,
                email=res.user.email,
                first_name=first_name,
                reservation_id=res.unique_id,
                payment_amount=f"{float(actual_paid):.2f}",
                payment_method="online",
                payment_date=payment_date_fmt,
                pdf_content=pdf_content,
                json_content=json_content
            )

            # SOLO si la reserva acaba de confirmarse por primera vez
            if not was_confirmed and res.status == "confirmed":
                background_tasks.add_task(
                    send_reservation_confirmed_email,
                    email=res.user.email,
                    first_name=first_name,
                    reservation_id=res.unique_id,
                    check_in=res.check_in.strftime("%d/%m/%Y"),
                    check_out=res.check_out.strftime("%d/%m/%Y"),
                    pdf_content=pdf_content,
                    json_content=json_content
                )

    return {"status": "received"}
