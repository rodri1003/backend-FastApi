import os
from pathlib import Path
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from app.core.config import settings

# Configuración de ConnectionConfig para FastMail
conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=False
)

fastmail = FastMail(conf)


def _get_schedule_info() -> dict:
    """Recupera las horas de check-in y check-out configuradas dinámicamente."""
    from app.db.session import SessionLocal
    from app.services.system_settings_service import get_checkin_time, get_checkout_time

    db = SessionLocal()
    try:
        return {
            "checkin_time": get_checkin_time(db),
            "checkout_time": get_checkout_time(db)
        }
    except Exception:
        return {
            "checkin_time": "15:00",
            "checkout_time": "11:00"
        }
    finally:
        db.close()


def _format_time_12h(time_str: str) -> str:
    """Convierte un string de hora en formato 24h (HH:MM) a 12h (h:mm AM/PM)."""
    try:
        from datetime import datetime
        t = datetime.strptime(time_str.strip(), "%H:%M")
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return time_str


def _get_hotel_info() -> dict:
    """Recupera la información del hotel dinámicamente de system_settings."""
    from app.db.session import SessionLocal
    from app.services.system_settings_service import get_setting

    db = SessionLocal()
    try:
        hotel_name = get_setting(db, "hotel_name", "AFE Resort & Spa")
        hotel_phone = get_setting(db, "hotel_phone", "")
        hotel_email = get_setting(db, "hotel_email", "")
        return {
            "name": hotel_name,
            "phone": hotel_phone,
            "email": hotel_email
        }
    except Exception:
        return {
            "name": "AFE Resort & Spa",
            "phone": "",
            "email": ""
        }
    finally:
        db.close()


async def send_welcome_email(email: str, first_name: str, password: str):
    """
    Envía un correo de bienvenida a un nuevo cliente con sus credenciales.
    """
    hotel = _get_hotel_info()
    hotel_name = hotel["name"]

    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: auto; padding: 40px; border: 1px solid #e2e8f0; border-radius: 24px; background-color: #ffffff;">
        <div style="text-align: center; margin-bottom: 40px;">
            <h1 style="color: #0f172a; margin-bottom: 10px; font-weight: 800;">¡Bienvenido a {hotel_name}!</h1>
            <p style="color: #64748b; font-size: 16px;">Donde el lujo no tiene límites.</p>
        </div>
        
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Hola <strong>{first_name}</strong>,</p>
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Nos complace darte la bienvenida a nuestra exclusiva comunidad. Hemos creado tu cuenta para que puedas gestionar tus reservaciones de forma personalizada.</p>
        
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 16px; padding: 24px; margin: 30px 0;">
            <h2 style="color: #0f172a; font-size: 14px; margin-top: 0; text-transform: uppercase; letter-spacing: 0.1em;">Tus credenciales de acceso:</h2>
            <p style="margin: 8px 0; color: #475569;"><strong>Usuario:</strong> {email}</p>
            <p style="margin: 8px 0; color: #475569;"><strong>Contraseña Temporal:</strong> <code style="background: #e2e8f0; padding: 2px 6px; border-radius: 4px;">{password}</code></p>
        </div>
        
        <p style="color: #334155; font-size: 14px; line-height: 1.6; font-style: italic;">Por razones de seguridad, te recomendamos cambiar tu contraseña en tu primer inicio de sesión.</p>
        
        <div style="text-align: center; margin-top: 40px;">
            <a href="{settings.NGROK_URL}" style="background-color: #D4AF37; color: #000000; padding: 16px 32px; border-radius: 12px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block;">ACCEDER A MI PORTAL</a>
        </div>
        
        <div style="margin-top: 60px; padding-top: 20px; border-top: 1px solid #f1f5f9; text-align: center;">
            <p style="color: #94a3b8; font-size: 12px;">Este es un correo automático, por favor no respondas a este mensaje.</p>
            <p style="color: #94a3b8; font-size: 12px;">© 2026 {hotel_name}</p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject=f"Bienvenido a {hotel_name} - Tus Credenciales",
        recipients=[email],
        body=html,
        subtype=MessageType.html
    )

    try:
        await fastmail.send_message(message)
        print(f"Email enviado exitosamente a {email}")
    except Exception as e:
        print(f"Error al enviar email: {str(e)}")


async def send_reservation_confirmed_email(
    email: str, 
    first_name: str, 
    reservation_id: str, 
    check_in: str, 
    check_out: str,
    pdf_content: bytes = None,
    json_content: bytes = None
):
    """
    Envía un correo notificando que la reservación ha sido confirmada (pago aprobado).
    Opcionalmente adjunta el PDF del DTE y el JSON del DTE.
    """
    hotel = _get_hotel_info()
    hotel_name = hotel["name"]
    has_attachments = pdf_content or json_content
    
    schedule = _get_schedule_info()
    checkin_t_formatted = _format_time_12h(schedule["checkin_time"])
    checkout_t_formatted = _format_time_12h(schedule["checkout_time"])
    
    dte_block_confirm = ""
    if has_attachments:
        dte_block_confirm = (
            '<div style="background-color: #fffbeb; border: 1px solid #fde68a; '
            'border-radius: 16px; padding: 20px; margin: 20px 0;">'
            '<h3 style="color: #92400e; font-size: 13px; margin-top: 0; '
            'text-transform: uppercase; letter-spacing: 0.1em;">'
            '📎 Documentos Tributarios Adjuntos</h3>'
            '<p style="margin: 6px 0; color: #78350f; font-size: 14px;">'
            'Adjunto a este correo encontrarás tu comprobante fiscal:</p>'
            '<ul style="color: #78350f; font-size: 13px; padding-left: 20px;">'
            '<li><strong>DTE.pdf</strong> — Representación gráfica del DTE</li>'
            '<li><strong>DTE.json</strong> — Documento tributario electrónico '
            '(formato estándar MH)</li></ul></div>'
        )

    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: auto; padding: 40px; border: 1px solid #e2e8f0; border-radius: 24px; background-color: #ffffff;">
        <div style="text-align: center; margin-bottom: 40px;">
            <h1 style="color: #0f172a; margin-bottom: 10px; font-weight: 800;">¡Tu Reservación está Confirmada!</h1>
            <p style="color: #64748b; font-size: 16px;">Nos complace recibirte en {hotel_name}.</p>
        </div>
        
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Hola <strong>{first_name}</strong>,</p>
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Hemos verificado y aprobado tu pago. Tu reservación <strong>#{reservation_id}</strong> ya se encuentra confirmada.</p>
        
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 16px; padding: 24px; margin: 30px 0;">
            <h2 style="color: #0f172a; font-size: 14px; margin-top: 0; text-transform: uppercase; letter-spacing: 0.1em;">Detalles de tu Estancia:</h2>
            <p style="margin: 8px 0; color: #475569;"><strong>Check-in:</strong> {check_in} (desde las {checkin_t_formatted})</p>
            <p style="margin: 8px 0; color: #475569;"><strong>Check-out:</strong> {check_out} (hasta las {checkout_t_formatted})</p>
        </div>

        {dte_block_confirm}
        
        <p style="color: #334155; font-size: 14px; line-height: 1.6; font-style: italic;">Te recomendamos revisar las políticas del hotel antes de tu llegada. ¡Buen viaje!</p>
        
        <div style="text-align: center; margin-top: 40px;">
            <a href="{settings.NGROK_URL}/profile/reservations" style="background-color: #D4AF37; color: #000000; padding: 16px 32px; border-radius: 12px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block;">VER MI RESERVACIÓN</a>
        </div>
        
        <div style="margin-top: 60px; padding-top: 20px; border-top: 1px solid #f1f5f9; text-align: center;">
            <p style="color: #94a3b8; font-size: 12px;">Este es un correo automático, por favor no respondas a este mensaje.</p>
            <p style="color: #94a3b8; font-size: 12px;">© 2026 {hotel_name}</p>
        </div>
    </div>
    """

    message_data = {
        "subject": f"Confirmación de Reservación #{reservation_id} — DTE",
        "recipients": [email],
        "body": html,
        "subtype": MessageType.html
    }

    attachments_to_clean = []

    if pdf_content or json_content:
        import tempfile
        attachment_paths = []
        
        if pdf_content:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="DTE_") as tmp:
                tmp.write(pdf_content)
                attachment_paths.append(tmp.name)
                attachments_to_clean.append(tmp.name)
        
        if json_content:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", prefix="DTE_") as tmp:
                tmp.write(json_content)
                attachment_paths.append(tmp.name)
                attachments_to_clean.append(tmp.name)
        
        message_data["attachments"] = attachment_paths

    message = MessageSchema(**message_data)

    try:
        await fastmail.send_message(message)
        print(f"Email de confirmación enviado exitosamente a {email}")
    except Exception as e:
        print(f"Error al enviar email de confirmación: {str(e)}")
    finally:
        for path in attachments_to_clean:
            try:
                os.remove(path)
            except:
                pass


async def send_payment_receipt_email(
    email: str,
    first_name: str,
    reservation_id: str,
    payment_amount: str,
    payment_method: str,
    payment_date: str,
    pdf_content: bytes = None,
    json_content: bytes = None
):
    """
    Envía un comprobante de pago al cliente cada vez que un pago se procesa
    exitosamente. Se usa tanto en el primer pago como en pagos posteriores
    (extras, incidentales). Es independiente del email de confirmación de reserva.
    """
    hotel = _get_hotel_info()
    hotel_name = hotel["name"]
    has_attachments = pdf_content or json_content

    # Normalizar método de pago a texto legible
    method_labels = {
        "cash": "Efectivo",
        "card": "Tarjeta de crédito/débito",
        "transfer": "Transferencia bancaria",
        "online": "Pago en línea (Wompi)",
    }
    method_display = method_labels.get(payment_method.lower(), payment_method.capitalize())

    dte_block_receipt = ""
    if has_attachments:
        dte_block_receipt = (
            '<div style="background-color: #fffbeb; border: 1px solid #fde68a; '
            'border-radius: 16px; padding: 20px; margin: 20px 0;">'
            '<h3 style="color: #92400e; font-size: 13px; margin: 0 0 8px 0; '
            'text-transform: uppercase; letter-spacing: 0.1em;">'
            '📎 Documento Tributario Electrónico (DTE)</h3>'
            '<p style="margin: 6px 0; color: #78350f; font-size: 14px;">'
            'Adjunto a este correo encontrarás tu comprobante fiscal:</p>'
            '<ul style="color: #78350f; font-size: 13px; padding-left: 20px; margin: 4px 0;">'
            '<li><strong>DTE.pdf</strong> — Representación gráfica del DTE</li>'
            '<li><strong>DTE.json</strong> — Documento tributario electrónico '
            '(formato estándar MH)</li></ul></div>'
        )

    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: auto; padding: 40px; border: 1px solid #dcfce7; border-radius: 24px; background-color: #ffffff;">
        <div style="text-align: center; margin-bottom: 40px;">
            <div style="background-color: #f0fdf4; width: 64px; height: 64px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 16px;">
                <span style="font-size: 32px;">✅</span>
            </div>
            <h1 style="color: #0f172a; margin: 0 0 10px 0; font-weight: 800;">Comprobante de Pago</h1>
            <p style="color: #64748b; font-size: 16px; margin: 0;">Tu pago ha sido procesado exitosamente.</p>
        </div>

        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Hola <strong>{first_name}</strong>,</p>
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Confirmamos que hemos recibido tu pago para la reservación <strong>#{reservation_id}</strong>. A continuación encontrarás el detalle:</p>

        <div style="background-color: #0f172a; border-radius: 20px; padding: 30px; margin: 30px 0; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1);">
            <h2 style="color: #D4AF37; font-size: 13px; margin: 0 0 20px 0; text-transform: uppercase; letter-spacing: 0.12em;">Detalles del Pago</h2>
            <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                <span style="color: #94a3b8; font-size: 13px;">Monto pagado:</span>
                <span style="color: #ffffff; font-size: 20px; font-weight: 800;">${payment_amount} USD</span>
            </div>
            <hr style="border: none; border-top: 1px solid #1e293b; margin: 16px 0;">
            <div style="margin-bottom: 8px;">
                <span style="color: #94a3b8; font-size: 12px;">Reservación:</span>
                <span style="color: #e2e8f0; font-size: 12px; margin-left: 8px;">#{reservation_id}</span>
            </div>
            <div style="margin-bottom: 8px;">
                <span style="color: #94a3b8; font-size: 12px;">Método:</span>
                <span style="color: #e2e8f0; font-size: 12px; margin-left: 8px;">{method_display}</span>
            </div>
            <div>
                <span style="color: #94a3b8; font-size: 12px;">Fecha:</span>
                <span style="color: #e2e8f0; font-size: 12px; margin-left: 8px;">{payment_date}</span>
            </div>
        </div>

        {dte_block_receipt}

        <p style="color: #64748b; font-size: 13px; line-height: 1.6; font-style: italic;">Conserva este correo como respaldo de tu pago. Si tienes alguna consulta, no dudes en contactarnos.</p>

        <div style="text-align: center; margin-top: 40px;">
            <a href="{settings.NGROK_URL}/profile/reservations" style="background-color: #D4AF37; color: #000000; padding: 16px 32px; border-radius: 12px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block;">VER MI RESERVACIÓN</a>
        </div>

        <div style="margin-top: 60px; padding-top: 20px; border-top: 1px solid #f1f5f9; text-align: center;">
            <p style="color: #94a3b8; font-size: 12px;">Este es un correo automático, por favor no respondas a este mensaje.</p>
            <p style="color: #94a3b8; font-size: 12px;">© 2026 {hotel_name}</p>
        </div>
    </div>
    """

    message_data = {
        "subject": f"Comprobante de Pago — Reserva #{reservation_id} — DTE",
        "recipients": [email],
        "body": html,
        "subtype": MessageType.html
    }

    attachments_to_clean = []

    if pdf_content or json_content:
        import tempfile
        attachment_paths = []

        if pdf_content:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="DTE_") as tmp:
                tmp.write(pdf_content)
                attachment_paths.append(tmp.name)
                attachments_to_clean.append(tmp.name)

        if json_content:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", prefix="DTE_") as tmp:
                tmp.write(json_content)
                attachment_paths.append(tmp.name)
                attachments_to_clean.append(tmp.name)

        message_data["attachments"] = attachment_paths

    message = MessageSchema(**message_data)

    try:
        await fastmail.send_message(message)
        print(f"Email de comprobante de pago enviado exitosamente a {email}")
    except Exception as e:
        print(f"Error al enviar email de comprobante de pago: {str(e)}")
    finally:
        for path in attachments_to_clean:
            try:
                os.remove(path)
            except:
                pass


async def send_reservation_cancelled_email(email: str, first_name: str, reservation_id: str, reason: str = "A solicitud del cliente"):
    """Notifica al cliente que su reservación ha sido cancelada."""
    hotel = _get_hotel_info()
    hotel_name = hotel["name"]

    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: auto; padding: 40px; border: 1px solid #fee2e2; border-radius: 24px; background-color: #ffffff;">
        <div style="text-align: center; margin-bottom: 40px;">
            <div style="background-color: #fef2f2; width: 64px; height: 64px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px;">
                <span style="font-size: 32px;">🛑</span>
            </div>
            <h1 style="color: #991b1b; margin-bottom: 10px; font-weight: 800;">Reservación Cancelada</h1>
            <p style="color: #64748b; font-size: 16px;">Confirmación de anulación de reserva.</p>
        </div>
        
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Hola <strong>{first_name}</strong>,</p>
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Te informamos que tu reservación <strong>#{reservation_id}</strong> ha sido cancelada exitosamente.</p>
        
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 16px; padding: 24px; margin: 30px 0;">
            <p style="margin: 0; color: #475569;"><strong>Motivo:</strong> {reason}</p>
        </div>

        <p style="color: #334155; font-size: 14px; line-height: 1.6;">Si esta cancelación fue un error o deseas realizar una nueva reservación, puedes hacerlo en cualquier momento desde nuestro portal.</p>
        
        <div style="text-align: center; margin-top: 40px;">
            <a href="{settings.NGROK_URL}" style="background-color: #0f172a; color: #ffffff; padding: 16px 32px; border-radius: 12px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block;">VOLVER AL SITIO</a>
        </div>
        
        <div style="margin-top: 60px; padding-top: 20px; border-top: 1px solid #f1f5f9; text-align: center;">
            <p style="color: #94a3b8; font-size: 12px;">© 2026 {hotel_name}</p>
        </div>
    </div>
    """
    message = MessageSchema(subject=f"Anulación de Reservación #{reservation_id}", recipients=[email], body=html, subtype=MessageType.html)
    try:
        await fastmail.send_message(message)
    except Exception as e:
        print(f"Error cancel email: {str(e)}")


async def send_payment_rejected_email(email: str, first_name: str, reservation_id: str, reason: str):
    """Notifica que un comprobante de pago fue rechazado."""
    hotel = _get_hotel_info()
    hotel_name = hotel["name"]

    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: auto; padding: 40px; border: 1px solid #fef3c7; border-radius: 24px; background-color: #ffffff;">
        <div style="text-align: center; margin-bottom: 40px;">
            <h1 style="color: #92400e; margin-bottom: 10px; font-weight: 800;">Atención: Pago no Verificado</h1>
            <p style="color: #64748b; font-size: 16px;">Requerimos acción adicional para confirmar tu estancia.</p>
        </div>
        
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Hola <strong>{first_name}</strong>,</p>
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Lamentamos informarte que no hemos podido verificar el comprobante de pago enviado para la reserva <strong>#{reservation_id}</strong>.</p>
        
        <div style="background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 16px; padding: 24px; margin: 30px 0;">
            <h3 style="color: #92400e; font-size: 14px; margin-top: 0; text-transform: uppercase;">Motivo del rechazo:</h3>
            <p style="margin: 8px 0; color: #78350f;">{reason}</p>
        </div>

        <p style="color: #334155; font-size: 14px; line-height: 1.6;">Por favor, ingresa a tu perfil para subir un comprobante válido o utiliza otro método de pago para asegurar tu habitación.</p>
        
        <div style="text-align: center; margin-top: 40px;">
            <a href="{settings.NGROK_URL}/profile/reservations" style="background-color: #D4AF37; color: #000000; padding: 16px 32px; border-radius: 12px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block;">CORREGIR PAGO</a>
        </div>
        
        <div style="margin-top: 60px; padding-top: 20px; border-top: 1px solid #f1f5f9; text-align: center;">
            <p style="color: #94a3b8; font-size: 12px;">© 2026 {hotel_name}</p>
        </div>
    </div>
    """
    message = MessageSchema(subject=f"Acción requerida: Pago no verificado - Reserva #{reservation_id}", recipients=[email], body=html, subtype=MessageType.html)
    try:
        await fastmail.send_message(message)
    except Exception as e:
        print(f"Error reject email: {str(e)}")


async def send_refund_processed_email(email: str, first_name: str, reservation_id: str, amount: str):
    """Notifica que se ha procesado un reembolso."""
    hotel = _get_hotel_info()
    hotel_name = hotel["name"]

    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: auto; padding: 40px; border: 1px solid #dcfce7; border-radius: 24px; background-color: #ffffff;">
        <div style="text-align: center; margin-bottom: 40px;">
            <h1 style="color: #166534; margin-bottom: 10px; font-weight: 800;">Reembolso Procesado</h1>
            <p style="color: #64748b; font-size: 16px;">Hemos devuelto el saldo a tu favor.</p>
        </div>
        
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Hola <strong>{first_name}</strong>,</p>
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Te confirmamos que se ha procesado un reembolso de <strong>${amount}</strong> asociado a tu reservación <strong>#{reservation_id}</strong>.</p>
        
        <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 16px; padding: 24px; margin: 30px 0; text-align: center;">
            <p style="margin: 0; color: #166534; font-size: 24px; font-weight: bold;">${amount} USD</p>
            <p style="margin: 4px 0 0; color: #15803d; font-size: 12px;">Monto acreditado</p>
        </div>

        <p style="color: #334155; font-size: 14px; line-height: 1.6;">Dependiendo de tu entidad bancaria, el monto podría tardar entre 3 a 5 días hábiles en verse reflejado en tu cuenta.</p>
        
        <div style="margin-top: 60px; padding-top: 20px; border-top: 1px solid #f1f5f9; text-align: center;">
            <p style="color: #94a3b8; font-size: 12px;">© 2026 {hotel_name}</p>
        </div>
    </div>
    """
    message = MessageSchema(subject=f"Reembolso Procesado - Reserva #{reservation_id}", recipients=[email], body=html, subtype=MessageType.html)
    try:
        await fastmail.send_message(message)
    except Exception as e:
        print(f"Error refund email: {str(e)}")


async def send_checkin_reminder_email(email: str, first_name: str, reservation_id: str, check_in: str, room_name: str):
    """Recordatorio de check-in 24h antes."""
    hotel = _get_hotel_info()
    hotel_name = hotel["name"]
    
    schedule = _get_schedule_info()
    checkin_t_formatted = _format_time_12h(schedule["checkin_time"])

    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: auto; padding: 40px; border: 1px solid #e2e8f0; border-radius: 24px; background-color: #ffffff; background-image: linear-gradient(to bottom, #ffffff, #f8fafc);">
        <div style="text-align: center; margin-bottom: 40px;">
            <p style="color: #D4AF37; font-weight: bold; text-transform: uppercase; letter-spacing: 0.2em; margin-bottom: 10px;">Tu aventura comienza pronto</p>
            <h1 style="color: #0f172a; margin-bottom: 10px; font-weight: 800;">¡Te esperamos mañana!</h1>
        </div>
        
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Hola <strong>{first_name}</strong>,</p>
        <p style="color: #334155; font-size: 16px; line-height: 1.6;">Falta muy poco para recibirte en {hotel_name}. Estamos preparando todo para que tu estancia sea inolvidable.</p>
        
        <div style="background-color: #0f172a; color: #ffffff; border-radius: 20px; padding: 30px; margin: 30px 0; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);">
            <h2 style="color: #D4AF37; font-size: 14px; margin-top: 0; text-transform: uppercase; letter-spacing: 0.1em;">Resumen de tu llegada:</h2>
            <div style="display: flex; margin-top: 20px;">
                <div style="flex: 1;">
                    <p style="margin: 0; color: #94a3b8; font-size: 12px;">Fecha:</p>
                    <p style="margin: 4px 0; font-weight: bold;">{check_in}</p>
                </div>
                <div style="flex: 1;">
                    <p style="margin: 0; color: #94a3b8; font-size: 12px;">Habitación:</p>
                    <p style="margin: 4px 0; font-weight: bold;">{room_name}</p>
                </div>
            </div>
            <p style="margin: 15px 0 0; color: #94a3b8; font-size: 12px;">Check-in: {checkin_t_formatted}</p>
        </div>

        <p style="color: #334155; font-size: 14px; line-height: 1.6;">Recuerda presentar tu documento de identidad al llegar. ¡Buen viaje!</p>
        
        <div style="text-align: center; margin-top: 40px;">
            <a href="https://maps.google.com" style="border: 1px solid #cbd5e1; color: #334155; padding: 16px 32px; border-radius: 12px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block;">¿CÓMO LLEGAR?</a>
        </div>
        
        <div style="margin-top: 60px; padding-top: 20px; border-top: 1px solid #f1f5f9; text-align: center;">
            <p style="color: #94a3b8; font-size: 12px;">© 2026 {hotel_name}</p>
        </div>
    </div>
    """
    message = MessageSchema(subject=f"¡Mañana es el gran día! - Reserva #{reservation_id}", recipients=[email], body=html, subtype=MessageType.html)
    try:
        await fastmail.send_message(message)
    except Exception as e:
        print(f"Error reminder email: {str(e)}")
