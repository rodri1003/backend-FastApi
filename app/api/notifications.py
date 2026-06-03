"""
Endpoints REST para el sistema de notificaciones del usuario autenticado.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.notification import NotificationRead, NotificationUnreadCount
from app.services import notification_service as ns

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationRead])
def list_my_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista las notificaciones del usuario autenticado (paginado)."""
    return ns.get_user_notifications(db, current_user.id, skip=skip, limit=limit, unread_only=unread_only)


@router.get("/unread-count", response_model=NotificationUnreadCount)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtiene la cantidad de notificaciones no leídas."""
    count = ns.get_unread_count(db, current_user.id)
    return NotificationUnreadCount(count=count)


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca una notificación como leída."""
    notif = ns.mark_as_read(db, notification_id, current_user.id)
    if not notif:
        raise HTTPException(status_code=404, detail="Notificación no encontrada.")
    return notif


@router.patch("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca todas las notificaciones del usuario como leídas."""
    count = ns.mark_all_as_read(db, current_user.id)
    return {"message": f"{count} notificaciones marcadas como leídas."}


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Elimina una notificación."""
    deleted = ns.delete_notification(db, notification_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notificación no encontrada.")
    return {"message": "Notificación eliminada."}
