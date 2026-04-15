import re
from typing import Any

def mask_pii(data: dict[str, Any]) -> dict[str, Any]:
    """
    Enmascara información sensible (PII) en un diccionario recursivamente.
    """
    if not isinstance(data, dict):
        return data

    masked = data.copy()
    
    # Patrones de búsqueda comunes para campos sensibles
    sensitive_keys = {
        "email", "EMail", "correo", "phone", "telefono", 
        "tarjeta", "pan", "card_number", "billing_address",
        "first_name", "last_name", "Nombre"
    }

    for key, value in masked.items():
        if isinstance(value, dict):
            masked[key] = mask_pii(value)
        elif isinstance(value, list):
            masked[key] = [mask_pii(item) if isinstance(item, dict) else item for item in value]
        elif any(s in key.lower() for s in sensitive_keys) and isinstance(value, str):
            if "@" in value: # Es un email
                parts = value.split("@")
                masked[key] = f"{parts[0][0]}***@{parts[1]}"
            elif len(value) > 4: # Es un teléfono o tarjeta
                masked[key] = f"{'*' * (len(value) - 4)}{value[-4:]}"
            else:
                masked[key] = "***"
                
    return masked
