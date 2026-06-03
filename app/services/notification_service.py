"""
Servicio central del sistema de notificaciones.
Gestiona creación, consulta, y dispatch automático basado en eventos del sistema.
"""
from sqlalchemy.orm import Session
from sqlalchemy import desc
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from app.db.session import SessionLocal

from app.models.notification import Notification, NotificationSetting
from app.models.user import User, UserRole, Role
from app.models.reservation import Reservation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuración global (lee de la tabla notification_settings)
# ---------------------------------------------------------------------------

def get_setting(db: Session, key: str) -> str | None:
    """Obtiene el valor de una configuración de notificaciones."""
    row = db.query(NotificationSetting).filter(NotificationSetting.key == key).first()
    return row.value if row else None


def get_all_settings(db: Session) -> list[NotificationSetting]:
    """Devuelve todas las configuraciones de notificaciones."""
    return db.query(NotificationSetting).order_by(NotificationSetting.key).all()


def update_setting(db: Session, key: str, value: str) -> NotificationSetting | None:
    """Actualiza una configuración existente."""
    row = db.query(NotificationSetting).filter(NotificationSetting.key == key).first()
    if not row:
        return None
    row.value = value
    db.commit()
    db.refresh(row)
    return row


def _is_enabled(db: Session, setting_key: str) -> bool:
    """Verifica si un tipo de notificación está habilitado."""
    # Primero verificar si el sistema completo está habilitado
    global_enabled = get_setting(db, "notifications_enabled")
    if global_enabled and global_enabled.lower() == "false":
        return False
    # Verificar la configuración específica
    val = get_setting(db, setting_key)
    if val is None:
        return True  # Por defecto habilitado si no existe la configuración
    return val.lower() == "true"


# ---------------------------------------------------------------------------
# CRUD de Notificaciones
# ---------------------------------------------------------------------------

def create_notification(
    db: Session,
    user_id: int,
    type: str,
    severity: str,
    title: str,
    message: str,
    reference_type: str | None = None,
    reference_id: int | None = None,
) -> Notification:
    """Crea una notificación para un usuario específico."""
    notif = Notification(
        user_id=user_id,
        type=type,
        severity=severity,
        title=title,
        message=message,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


def get_user_notifications(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
    unread_only: bool = False,
) -> list[Notification]:
    """Obtiene las notificaciones de un usuario, ordenadas por más recientes."""
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    return query.order_by(desc(Notification.created_at)).offset(skip).limit(limit).all()


def get_unread_count(db: Session, user_id: int) -> int:
    """Cuenta las notificaciones no leídas de un usuario."""
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)
        .count()
    )


def mark_as_read(db: Session, notification_id: int, user_id: int) -> Notification | None:
    """Marca una notificación como leída (solo si pertenece al usuario)."""
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not notif:
        return None
    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


def mark_all_as_read(db: Session, user_id: int) -> int:
    """Marca todas las notificaciones del usuario como leídas. Retorna la cantidad actualizada."""
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)
        .update({"is_read": True})
    )
    db.commit()
    return count


def delete_notification(db: Session, notification_id: int, user_id: int) -> bool:
    """Elimina una notificación (solo si pertenece al usuario)."""
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not notif:
        return False
    db.delete(notif)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _get_admin_user_ids(db: Session) -> list[int]:
    """Obtiene los IDs de todos los usuarios con roles administrativos configurados en 'admin_notification_roles'."""
    roles_str = get_setting(db, "admin_notification_roles")
    if not roles_str:
        roles_str = "admin,gerente,editor"
        
    role_names = [r.strip() for r in roles_str.split(",") if r.strip()]
    
    admin_roles = db.query(Role).filter(Role.name.in_(role_names)).all()
    if not admin_roles:
        return []
    
    role_ids = [r.id for r in admin_roles]
    rows = db.query(UserRole.user_id).filter(UserRole.role_id.in_(role_ids)).all()
    return list(set(r[0] for r in rows)) # Usar set para evitar duplicados si un usuario tiene múltiples roles


# ---------------------------------------------------------------------------
# Dispatch automático: Reservas
# ---------------------------------------------------------------------------

def notify_reservation_created(db: Session, reservation: Reservation) -> None:
    """Notifica al cliente y a los admins cuando se crea una reserva."""
    # Notificar al cliente
    if _is_enabled(db, "notify_client_reservation_created"):
        create_notification(
            db,
            user_id=reservation.user_id,
            type="reservation",
            severity="success",
            title="Reserva Creada",
            message=f"Tu reserva #{reservation.unique_id} ha sido registrada exitosamente. Total: ${reservation.total_cost:.2f}",
            reference_type="reservation",
            reference_id=reservation.id,
        )

    # Notificar a los admins
    if _is_enabled(db, "notify_admin_new_reservation"):
        admin_ids = _get_admin_user_ids(db)
        for admin_id in admin_ids:
            create_notification(
                db,
                user_id=admin_id,
                type="reservation",
                severity="info",
                title="Nueva Reserva",
                message=f"Se ha creado la reserva #{reservation.unique_id} por un total de ${reservation.total_cost:.2f}.",
                reference_type="reservation",
                reference_id=reservation.id,
            )


def notify_reservation_confirmed(db: Session, reservation: Reservation) -> None:
    """Notifica al cliente cuando su reserva es confirmada."""
    if _is_enabled(db, "notify_client_reservation_confirmed"):
        create_notification(
            db,
            user_id=reservation.user_id,
            type="reservation",
            severity="success",
            title="Reserva Confirmada",
            message=f"¡Tu reserva #{reservation.unique_id} ha sido confirmada! Te esperamos.",
            reference_type="reservation",
            reference_id=reservation.id,
        )


def notify_reservation_cancelled(db: Session, reservation: Reservation, cancelled_by: str = "system") -> None:
    """Notifica cuando una reserva es cancelada."""
    # Siempre notificar al cliente
    if _is_enabled(db, "notify_client_reservation_cancelled"):
        if cancelled_by == "system":
            msg = f"Tu reserva #{reservation.unique_id} fue cancelada automáticamente por tiempo de pago expirado."
        elif cancelled_by == "admin":
            msg = f"Tu reserva #{reservation.unique_id} ha sido cancelada por el administrador."
        else:
            msg = f"Tu reserva #{reservation.unique_id} ha sido cancelada exitosamente."

        create_notification(
            db,
            user_id=reservation.user_id,
            type="reservation",
            severity="warning",
            title="Reserva Cancelada",
            message=msg,
            reference_type="reservation",
            reference_id=reservation.id,
        )

    # Notificar a los admins (excepto si fue el admin quien canceló)
    if cancelled_by != "admin" and _is_enabled(db, "notify_admin_reservation_cancelled"):
        admin_ids = _get_admin_user_ids(db)
        for admin_id in admin_ids:
            create_notification(
                db,
                user_id=admin_id,
                type="reservation",
                severity="warning",
                title="Reserva Cancelada",
                message=f"La reserva #{reservation.unique_id} fue cancelada ({cancelled_by}).",
                reference_type="reservation",
                reference_id=reservation.id,
            )


# ---------------------------------------------------------------------------
# Dispatch automático: Pagos
# ---------------------------------------------------------------------------

def notify_payment_received(db: Session, reservation: Reservation, amount) -> None:
    """Notifica al cliente y admins cuando se recibe un pago."""
    if _is_enabled(db, "notify_client_payment_received"):
        create_notification(
            db,
            user_id=reservation.user_id,
            type="payment",
            severity="success",
            title="Pago Recibido",
            message=f"Se ha registrado un pago de ${float(amount):.2f} para tu reserva #{reservation.unique_id}.",
            reference_type="reservation",
            reference_id=reservation.id,
        )

    if _is_enabled(db, "notify_admin_payment_received"):
        admin_ids = _get_admin_user_ids(db)
        for admin_id in admin_ids:
            create_notification(
                db,
                user_id=admin_id,
                type="payment",
                severity="info",
                title="Pago Recibido",
                message=f"Pago de ${float(amount):.2f} recibido para reserva #{reservation.unique_id}.",
                reference_type="reservation",
                reference_id=reservation.id,
            )

# ---------------------------------------------------------------------------
# Dispatch automático: Cargos Incidentales
# ---------------------------------------------------------------------------

def notify_incidental_charge_created(db: Session, reservation: Reservation, charge) -> None:
    """Notifica al cliente y a los admins cuando se registra un cargo incidental."""
    # Intentar notificar al cliente (siempre por defecto o si está habilitado)
    create_notification(
        db,
        user_id=reservation.user_id,
        type="incidental",
        severity="warning",
        title="Nuevo Cargo Registrado",
        message=f"Se ha registrado un cargo de ${float(charge.total_amount):.2f} en tu reserva #{reservation.unique_id}: {charge.description}",
        reference_type="reservation",
        reference_id=reservation.id,
    )

    # Notificar a los admins
    admin_ids = _get_admin_user_ids(db)
    for admin_id in admin_ids:
        create_notification(
            db,
            user_id=admin_id,
            type="incidental",
            severity="info",
            title="Cargo Incidental Registrado",
            message=f"Se ha registrado un cargo incidental de ${float(charge.total_amount):.2f} ({charge.description}) en reserva #{reservation.unique_id}.",
            reference_type="reservation",
            reference_id=reservation.id,
        )


def notify_incidental_charge_waived(db: Session, reservation: Reservation, charge) -> None:
    """Notifica al cliente cuando un cargo incidental es condonado."""
    create_notification(
        db,
        user_id=reservation.user_id,
        type="incidental",
        severity="success",
        title="Cargo Condonado",
        message=f"El cargo de ${float(charge.total_amount):.2f} ({charge.description}) en tu reserva #{reservation.unique_id} ha sido condonado.",
        reference_type="reservation",
        reference_id=reservation.id,
    )


# ---------------------------------------------------------------------------
# Tareas de Segundo Plano (Background Tasks)
# ---------------------------------------------------------------------------

async def auto_cleanup_old_notifications():
    """
    Tarea en segundo plano que corre diariamente para eliminar notificaciones antiguas
    según la configuración 'notification_retention_days'.
    """
    logger.info("Iniciando demonio de limpieza automática de notificaciones...")
    while True:
        try:
            db = SessionLocal()
            try:
                retention_setting = get_setting(db, "notification_retention_days")
                
                days = 90
                if retention_setting:
                    if str(retention_setting).lower() == "false":
                        days = 0 # 0 means disabled
                    else:
                        try:
                            days = int(retention_setting)
                        except ValueError:
                            days = 90
                
                if days > 0:
                    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                    deleted_count = db.query(Notification).filter(Notification.created_at < cutoff_date).delete(synchronize_session=False)
                    db.commit()
                    if deleted_count > 0:
                        logger.info(f"Limpieza de notificaciones: {deleted_count} eliminadas (antigüedad > {days} días).")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error en auto_cleanup_old_notifications: {e}")
            
        # Esperar 24 horas antes de la siguiente revisión
        await asyncio.sleep(86400)
