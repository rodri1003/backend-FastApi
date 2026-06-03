from datetime import datetime, date
import pytz

EL_SALVADOR_TZ = pytz.timezone('America/El_Salvador')

def get_el_salvador_now() -> datetime:
    """Returns the current datetime in El Salvador timezone."""
    return datetime.now(EL_SALVADOR_TZ)

def get_el_salvador_today() -> date:
    """Returns the current date in El Salvador timezone."""
    return get_el_salvador_now().date()

def format_payment_datetime(dt: datetime = None) -> str:
    """
    Formats a datetime as 'DD/MM/YYYY H:MM AM/PM' in El Salvador locale.
    Uses cross-platform compatible strftime (avoids %-I which is Linux-only).
    If no datetime provided, uses the current El Salvador time.
    """
    if dt is None:
        dt = get_el_salvador_now()
    # %I gives zero-padded 12h hour; lstrip removes leading zero for clean display
    raw = dt.strftime("%d/%m/%Y %I:%M %p")
    # Remove leading zero from hour: "08:30 AM" -> "8:30 AM"
    parts = raw.split(" ")
    parts[1] = parts[1].lstrip("0") or "12"
    return " ".join(parts)
