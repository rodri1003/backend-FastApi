"""
Servicio para gestionar la configuración general del sistema.
Implementa cache en memoria para minimizar las consultas a la base de datos.
"""
import logging
from sqlalchemy.orm import Session

from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# Cache en memoria para alto rendimiento
_settings_cache: dict[str, str] = {}


def get_all_settings(db: Session) -> list[SystemSetting]:
    """Obtiene todas las configuraciones del sistema."""
    return db.query(SystemSetting).order_by(SystemSetting.key).all()


def get_settings_by_category(db: Session, category: str) -> list[SystemSetting]:
    """Obtiene configuraciones filtradas por categoría."""
    return db.query(SystemSetting).filter(SystemSetting.category == category).order_by(SystemSetting.key).all()


def get_setting(db: Session, key: str, default: str = "") -> str:
    """
    Obtiene el valor de una configuración del sistema por su clave.
    Utiliza cache en memoria.
    """
    global _settings_cache
    if key in _settings_cache:
        return _settings_cache[key]

    setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    val = setting.value if setting else default
    _settings_cache[key] = val
    return val


def update_setting(db: Session, key: str, value: str) -> SystemSetting | None:
    """
    Actualiza una configuración individual e invalida la cache.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not setting:
        return None

    setting.value = value
    db.commit()
    db.refresh(setting)

    # Invalidar cache
    invalidate_cache()
    return setting


def bulk_update_settings(db: Session, updates: dict[str, str]) -> int:
    """
    Actualiza múltiples configuraciones de una vez e invalida la cache.
    Retorna la cantidad de registros actualizados.
    """
    if not updates:
        return 0

    updated_count = 0
    for key, value in updates.items():
        setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if setting:
            setting.value = value
            updated_count += 1

    if updated_count > 0:
        db.commit()
        # Invalidar cache
        invalidate_cache()

    return updated_count


def invalidate_cache() -> None:
    """Limpia la cache en memoria."""
    global _settings_cache
    _settings_cache.clear()
    logger.debug("Cache de configuraciones del sistema invalidada.")


# ---------------------------------------------------------------------------
# Helpers Tipados para Consumo de Negocio
# ---------------------------------------------------------------------------

def get_tax_iva(db: Session) -> float:
    """
    Retorna el porcentaje de IVA en decimales (ej. 13% -> 0.13).
    Usa 0.13 como valor de fallback de seguridad.
    """
    val_str = get_setting(db, "tax_iva_rate", "13.00")
    try:
        return float(val_str) / 100.0
    except ValueError:
        return 0.13


def get_tax_tourism(db: Session) -> float:
    """
    Retorna el porcentaje del impuesto al turismo municipal en decimales (ej. 5% -> 0.05).
    Usa 0.05 como fallback.
    """
    val_str = get_setting(db, "tax_tourism_rate", "5.00")
    try:
        return float(val_str) / 100.0
    except ValueError:
        return 0.05


def get_cancellation_policy(db: Session) -> dict:
    """
    Retorna la política de cancelación estructurada.
    """
    try:
        same_day_penalty = float(get_setting(db, "cancellation_same_day_penalty", "100"))
    except ValueError:
        same_day_penalty = 100.0

    try:
        short_notice_days = int(get_setting(db, "cancellation_short_notice_days", "2"))
    except ValueError:
        short_notice_days = 2

    try:
        short_notice_penalty = float(get_setting(db, "cancellation_short_notice_penalty", "20"))
    except ValueError:
        short_notice_penalty = 20.0

    return {
        "same_day_penalty": same_day_penalty,
        "short_notice_days": short_notice_days,
        "short_notice_penalty": short_notice_penalty,
    }


def get_checkin_time(db: Session) -> str:
    """Retorna la hora estándar de entrada (ej: '15:00')."""
    return get_setting(db, "checkin_time", "15:00")


def get_checkout_time(db: Session) -> str:
    """Retorna la hora estándar de salida (ej: '11:00')."""
    return get_setting(db, "checkout_time", "11:00")


def seed_defaults(db: Session) -> None:
    """
    Pobla la tabla system_settings con los valores por defecto si no existen.
    Es un seed idempotente para simplificar el despliegue.
    """
    defaults = [
        ("checkin_time", "15:00", "schedule", "Hora estándar de check-in"),
        ("checkout_time", "11:00", "schedule", "Hora estándar de check-out"),
        ("tax_iva_rate", "13.00", "taxes", "Porcentaje de IVA aplicable"),
        ("tax_tourism_rate", "5.00", "taxes", "Porcentaje de impuesto de turismo"),
        ("cancellation_same_day_penalty", "100", "cancellation", "Penalidad (%) por cancelación el mismo día"),
        ("cancellation_short_notice_days", "2", "cancellation", "Días de umbral para aviso corto"),
        ("cancellation_short_notice_penalty", "20", "cancellation", "Penalidad (%) por cancelación con aviso corto"),
        ("pending_reservation_timeout_hours", "24", "reservations", "Horas para expirar reservas pendientes"),
        ("max_stay_nights", "30", "reservations", "Máximo de noches por reservación"),
        ("min_advance_booking_days", "0", "reservations", "Días mínimos de anticipación para reservar"),
        ("hotel_name", "AFE Resort & Spa", "general", "Nombre del establecimiento"),
        ("hotel_phone", "", "general", "Teléfono principal de contacto"),
        ("hotel_email", "", "general", "Correo de contacto principal"),
        ("default_currency", "USD", "general", "Moneda de operación"),
        ("featured_amenity_filters", "1,4,12,21,24", "general", "IDs de amenidades de habitación para mostrar como filtros en la parte pública"),
        ("hero_image_reservations", "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?q=80&w=2070&auto=format&fit=crop", "general", "URL de la imagen de fondo para 'Mis Reservas'"),
        ("hero_images_rooms", "https://images.unsplash.com/photo-1611043704267-e67464e2351c?auto=format&fit=crop&w=1920&q=80,https://plus.unsplash.com/premium_photo-1682913629540-3857602b540c?auto=format&fit=crop&w=1920&q=80,https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?auto=format&fit=crop&w=1920&q=80,https://images.unsplash.com/photo-1578458329607-534298aebc4d?auto=format&fit=crop&w=1920&q=80", "general", "URLs de las imágenes del carrusel de 'Habitaciones' separadas por comas"),
        ("featured_rooms_home", "", "general", "IDs de habitaciones destacadas para mostrar en la página de inicio (vacío para mostrar las 3 primeras por defecto)"),
        ("hero_title", "Lujo sin concesiones.", "general", "Título principal en la portada pública"),
        ("hero_subtitle", "Descubre una experiencia arquitectónica y de hospitalidad diseñada para exceder cada una de tus expectativas.", "general", "Subtítulo secundario en la portada pública"),
        ("hero_video_url", "/videos/hotel-hero-video2.mp4", "general", "Enlace del video de fondo cinematográfico de portada"),
        ("esencia_img_main", "https://images.unsplash.com/photo-1529316275402-0462fcc4abd6?q=80&w=1471&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", "general", "Imagen principal de la sección Nuestra Esencia"),
        ("esencia_img_secondary", "https://images.unsplash.com/photo-1596436889106-be35e843f974?q=80&w=1470&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", "general", "Imagen secundaria de la sección Nuestra Esencia"),
        ("amenity_sig_1_img", "https://images.unsplash.com/photo-1514933651103-005eec06c04b?auto=format&fit=crop&w=400&q=80", "general", "Imagen de la Amenidad Signature 1"),
        ("amenity_sig_1_title", "Gastronomía Premium", "general", "Título de la Amenidad Signature 1"),
        ("amenity_sig_1_desc", "Alta cocina internacional con ingredientes orgánicos, cava subterránea y chefs galardonados estrella Michelín a su entera disposición.", "general", "Descripción de la Amenidad Signature 1"),
        ("amenity_sig_2_img", "https://images.unsplash.com/photo-1540555700478-4be289fbecef?auto=format&fit=crop&w=400&q=80", "general", "Imagen de la Amenidad Signature 2"),
        ("amenity_sig_2_title", "Spa Subterráneo", "general", "Título de la Amenidad Signature 2"),
        ("amenity_sig_2_desc", "Santuario holístico minimalista con circuitos termales, rituales de hidroterapia con sales volcánicas y masajes de rejuvenecimiento.", "general", "Descripción de la Amenidad Signature 2"),
        ("amenity_sig_3_img", "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=400&q=80", "general", "Imagen de la Amenidad Signature 3"),
        ("amenity_sig_3_title", "Concierge Privado", "general", "Título de la Amenidad Signature 3"),
        ("amenity_sig_3_desc", "Organización de itinerarios completamente personalizados, servicio de chofer y acceso VIP ilimitado a experiencias exclusivas.", "general", "Descripción de la Amenidad Signature 3"),
        ("momentos_video_url", "/videos/video-activities.mp4", "general", "Enlace del video de la sección Momentos Únicos"),
        ("momentos_img_url", "https://images.unsplash.com/photo-1506059612708-99d6c258160e?q=80&w=1469&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", "general", "Imagen flotante decorativa de la sección Momentos Únicos"),
        ("social_instagram", "#", "general", "Enlace de la cuenta de Instagram en el pie de página"),
        ("social_twitter", "#", "general", "Enlace de la cuenta de Twitter en el pie de página"),
        ("social_facebook", "#", "general", "Enlace de la cuenta de Facebook en el pie de página"),
        ("faq_items_json", '[\n  {"question": "¿Cuál es el horario de Check-in y Check-out?", "answer": "El horario estándar de Check-in es a partir de las 15:00 horas, permitiéndole ingresar a nuestras suites inmersivas de lujo. El Check-out es a las 11:00 horas para asegurar la preparación óptima de las habitaciones."},\n  {"question": "¿El resort cuenta con políticas de cancelación flexible?", "answer": "Sí, ofrecemos cancelación sin penalidad hasta 48 horas antes de su llegada programada para reservaciones estándar. Para tarifas promocionales o de alta temporada, se aplican términos específicos que podrá revisar al momento de confirmar su suite."},\n  {"question": "¿Tienen servicio de traslado desde el aeropuerto?", "answer": "Absolutamente. AFE Resort & Spa ofrece traslados privados en vehículos híbridos de alta gama. Este servicio puede coordinarse con nuestro Concierge Privado con un mínimo de 24 horas de anticipación."},\n  {"question": "¿Se permiten mascotas en el establecimiento?", "answer": "Contamos con suites especialmente acondicionadas para recibir a sus acompañantes caninos (máximo 15kg). Aplica una tarifa única de sanitización y es indispensable notificarlo durante el proceso de reservación."}\n]', "general", "Lista estructurada en JSON de Preguntas Frecuentes"),
        ("map_address", "Km. 14.5, Carretera Costera del Sol, Bahía Paraíso, Escuintla", "general", "Dirección física del hotel"),
        ("map_phone", "+502 7820-2400", "general", "Teléfono público de contacto"),
        ("map_email", "concierge@aferesort.com", "general", "Email principal de contacto"),
        ("map_hours", "Check-in: 15:00 | Check-out: 11:00 (Recepción 24/7)", "general", "Horarios estándar de operación"),
        ("map_iframe_url", "https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d15443.468711413807!2d-90.78564257121703!3d14.606828551465225!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x8589078491321703%3A0xe6a8a2524458f3de!2sAFE%20Resort%20%26%20Spa!5e0!3m2!1ses-419!2sgt!4v1716654000000!5m2!1ses-419!2sgt", "general", "URL del mapa embebido de Google Maps (src del iframe)")
    ]

    updated = False
    for key, value, category, desc in defaults:
        exists = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not exists:
            db.add(SystemSetting(key=key, value=value, category=category, description=desc))
            updated = True

    if updated:
        db.commit()
        logger.info("Valores por defecto de configuraciones inicializados en la BD.")
