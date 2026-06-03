"""
Endpoints REST para gestionar las configuraciones generales del sistema (Admin).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.permissions.deps import require_permission
from app.schemas.system_setting import SystemSettingBulkUpdate, SystemSettingRead, SystemSettingUpdate
from app.services import system_settings_service as sss

router = APIRouter(prefix="/admin/settings", tags=["System Settings"])


@router.get("", response_model=list[SystemSettingRead])
def list_system_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("settings", "read")),
):
    """Obtiene todas las configuraciones del sistema."""
    return sss.get_all_settings(db)


@router.get("/public")
def get_public_settings(db: Session = Depends(get_db)):
    """Obtiene las configuraciones del sistema públicas (incluyendo el contenido visual e informativo del portal)."""
    return {
        "tax_iva_rate": sss.get_tax_iva(db),
        "tax_tourism_rate": sss.get_tax_tourism(db),
        "featured_amenity_filters": sss.get_setting(db, "featured_amenity_filters", ""),
        "hero_image_reservations": sss.get_setting(db, "hero_image_reservations", ""),
        "hero_images_rooms": sss.get_setting(db, "hero_images_rooms", ""),
        "featured_rooms_home": sss.get_setting(db, "featured_rooms_home", ""),
        
        # Nuevas configuraciones de contenido del portal
        "hero_title": sss.get_setting(db, "hero_title", "Lujo sin concesiones."),
        "hero_subtitle": sss.get_setting(db, "hero_subtitle", "Descubre una experiencia arquitectónica y de hospitalidad diseñada para exceder cada una de tus expectativas."),
        "hero_video_url": sss.get_setting(db, "hero_video_url", "/videos/hotel-hero-video2.mp4"),
        
        "esencia_img_main": sss.get_setting(db, "esencia_img_main", "https://images.unsplash.com/photo-1529316275402-0462fcc4abd6?q=80&w=1471&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D"),
        "esencia_img_secondary": sss.get_setting(db, "esencia_img_secondary", "https://images.unsplash.com/photo-1596436889106-be35e843f974?q=80&w=1470&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D"),
        
        "amenity_sig_1_img": sss.get_setting(db, "amenity_sig_1_img", "https://images.unsplash.com/photo-1514933651103-005eec06c04b?auto=format&fit=crop&w=400&q=80"),
        "amenity_sig_1_title": sss.get_setting(db, "amenity_sig_1_title", "Gastronomía Premium"),
        "amenity_sig_1_desc": sss.get_setting(db, "amenity_sig_1_desc", "Alta cocina internacional con ingredientes orgánicos, cava subterránea y chefs galardonados estrella Michelín a su entera disposición."),
        
        "amenity_sig_2_img": sss.get_setting(db, "amenity_sig_2_img", "https://images.unsplash.com/photo-1540555700478-4be289fbecef?auto=format&fit=crop&w=400&q=80"),
        "amenity_sig_2_title": sss.get_setting(db, "amenity_sig_2_title", "Spa Subterráneo"),
        "amenity_sig_2_desc": sss.get_setting(db, "amenity_sig_2_desc", "Santuario holístico minimalista con circuitos termales, rituales de hidroterapia con sales volcánicas y masajes de rejuvenecimiento."),
        
        "amenity_sig_3_img": sss.get_setting(db, "amenity_sig_3_img", "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=400&q=80"),
        "amenity_sig_3_title": sss.get_setting(db, "amenity_sig_3_title", "Concierge Privado"),
        "amenity_sig_3_desc": sss.get_setting(db, "amenity_sig_3_desc", "Organización de itinerarios completamente personalizados, servicio de chofer y acceso VIP ilimitado a experiencias exclusivas."),
        
        "momentos_video_url": sss.get_setting(db, "momentos_video_url", "/videos/video-activities.mp4"),
        "momentos_img_url": sss.get_setting(db, "momentos_img_url", "https://images.unsplash.com/photo-1506059612708-99d6c258160e?q=80&w=1469&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D"),
        
        "social_instagram": sss.get_setting(db, "social_instagram", "#"),
        "social_twitter": sss.get_setting(db, "social_twitter", "#"),
        "social_facebook": sss.get_setting(db, "social_facebook", "#"),
        
        # Preguntas Frecuentes y Encuéntranos/Contacto
        "faq_items_json": sss.get_setting(db, "faq_items_json", "[]"),
        "map_address": sss.get_setting(db, "map_address", ""),
        "map_phone": sss.get_setting(db, "map_phone", ""),
        "map_email": sss.get_setting(db, "map_email", ""),
        "map_hours": sss.get_setting(db, "map_hours", ""),
        "map_iframe_url": sss.get_setting(db, "map_iframe_url", ""),
    }



@router.get("/category/{category}", response_model=list[SystemSettingRead])
def list_system_settings_by_category(
    category: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("settings", "read")),
):
    """Obtiene configuraciones filtradas por categoría."""
    return sss.get_settings_by_category(db, category)


@router.put("/bulk")
def bulk_update_settings(
    payload: SystemSettingBulkUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("settings", "update")),
):
    """
    Actualiza múltiples configuraciones de una vez.
    Payload: { "settings": { "key1": "value1", "key2": "value2" } }
    """
    updated_count = sss.bulk_update_settings(db, payload.settings)
    return {"message": f"Se actualizaron {updated_count} configuraciones exitosamente."}


@router.put("/{key}", response_model=SystemSettingRead)
def update_single_setting(
    key: str,
    payload: SystemSettingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("settings", "update")),
):
    """Actualiza una configuración individual por su clave."""
    setting = sss.update_setting(db, key, payload.value)
    if not setting:
        raise HTTPException(
            status_code=404,
            detail=f"La configuración con la clave '{key}' no existe.",
        )
    return setting
