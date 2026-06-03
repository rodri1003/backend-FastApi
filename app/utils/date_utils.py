from datetime import datetime, date
import pytz

EL_SALVADOR_TZ = pytz.timezone('America/El_Salvador')

def get_el_salvador_now() -> datetime:
    """Returns the current datetime in El Salvador timezone."""
    return datetime.now(EL_SALVADOR_TZ)

def get_el_salvador_today() -> date:
    """Returns the current date in El Salvador timezone."""
    return get_el_salvador_now().date()
