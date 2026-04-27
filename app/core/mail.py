import os
from pathlib import Path
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from app.core.config import settings

# Configuración de ConnectionConfig para FastMail
# Usamos los settings definidos en app.core.config
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
    VALIDATE_CERTS=True
)

fastmail = FastMail(conf)

async def send_welcome_email(email: str, first_name: str, password: str):
    """
    Envía un correo de bienvenida a un nuevo cliente con sus credenciales.
    """
    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: auto; padding: 40px; border: 1px solid #e2e8f0; border-radius: 24px; background-color: #ffffff;">
        <div style="text-align: center; margin-bottom: 40px;">
            <h1 style="color: #0f172a; margin-bottom: 10px; font-weight: 800;">¡Bienvenido a AFE Resort!</h1>
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
            <p style="color: #94a3b8; font-size: 12px;">© 2026 AFE Resort & Spa</p>
        </div>
    </div>
    """

    message = MessageSchema(
        subject="Bienvenido a AFE Resort - Tus Credenciales",
        recipients=[email],
        body=html,
        subtype=MessageType.html
    )

    # Nota: En un entorno de producción real, esto debería ir a una cola de tareas (Celery/RabbitMQ)
    # pero para este proyecto lo haremos asíncrono directamente.
    try:
        await fastmail.send_message(message)
        print(f"Email enviado exitosamente a {email}")
    except Exception as e:
        print(f"Error al enviar email: {str(e)}")
        # No levantamos excepción para no romper el flujo de creación de usuario si falla el mail
