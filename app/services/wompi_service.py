import httpx
from fastapi import HTTPException
import logging
import os

import json
from app.core.config import settings
from app.core.logging_utils import mask_pii

logger = logging.getLogger(__name__)

TOKEN_URL = "https://id.wompi.sv/connect/token"
ENLACE_URL = "https://api.wompi.sv/EnlacePago"

async def get_wompi_token() -> str:
    """Busca el token de acceso OAuth2 para Wompi El Salvador."""
    try:
        async with httpx.AsyncClient() as client:
            data = {
                "grant_type": "client_credentials",
                "client_id": settings.WOMPI_APP_ID,
                "client_secret": settings.WOMPI_API_SECRET,
                "audience": "wompi_api"
            }
            response = await client.post(TOKEN_URL, data=data, timeout=10.0)
            response.raise_for_status()
            token_data = response.json()
            return token_data.get("access_token")
    except Exception as e:
        logger.error(f"Error obtaining Wompi SV token: {e}")
        raise HTTPException(status_code=502, detail="Error de conexión con Wompi SV (Auth)")

async def generate_wompi_payment_link(reservation_uid: str, amount: float, redirect_url: str) -> str:
    """
    Genera un Enlace de Pago en Wompi SV para una reservación.
    Retorna la URL (urlEnlace) a la que el usuario o admin debe ser redirigido.
    """
    token = await get_wompi_token()
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "identificadorEnlaceComercio": reservation_uid,
        "monto": float(amount),
        "nombreProducto": f"Reservación de Habitación {reservation_uid}",
        "formaPago": {
            "permitirTarjetaCreditoDebido": True,
            "permitirPagoConPuntoAgricola": False
        },
        "configuracion": {
            "urlRedirect": redirect_url,
            "esMontoEditable": False,
            "esCantidadEditable": False,
            "urlWebhook": f"{settings.NGROK_URL}/webhooks/wompi",
            "notificarTransaccionCliente": False
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(ENLACE_URL, headers=headers, json=payload, timeout=15.0)
            
            if response.status_code != 200:
                try:
                    error_json = response.json()
                    masked_error = mask_pii(error_json)
                    logger.error(f"Wompi Link Error: {json.dumps(masked_error)}")
                except:
                    logger.error(f"Wompi Link Error (Raw): {response.text[:200]}")
                raise HTTPException(status_code=502, detail=f"Wompi rechazó la creación del enlace de pago")
                
            data = response.json()
            return data.get("urlEnlace")
    except httpx.RequestError as e:
        logger.error(f"HTTP Error calling Wompi SV EnlacePago: {e}")
        raise HTTPException(status_code=502, detail="Error de conexión con la pasarela de pagos Wompi SV")
