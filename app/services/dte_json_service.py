"""
Generador de JSON DTE (Documento Tributario Electrónico) simulado.
Sigue la estructura oficial del Ministerio de Hacienda de El Salvador.
"""
import json
import uuid
import hashlib
import base64
import random
from datetime import datetime


def generate_dte_json(receipt_data: dict) -> bytes:
    """
    Genera un JSON DTE simulado con la estructura oficial de Hacienda SV.
    Retorna bytes listos para adjuntar al email.
    """
    now = datetime.now()
    payment_id = str(receipt_data.get("payment_id", random.randint(1000, 9999)))
    is_fiscal = receipt_data.get("receipt_type") == "fiscal_credit"
    amount_paid = float(receipt_data.get("amount_paid", 0))

    # Cálculos fiscales
    base = amount_paid / 1.18
    iva = base * 0.13
    tourism = base * 0.05
    gravada = base if is_fiscal else (base + iva)

    # UUIDs deterministas basados en el payment_id para consistencia
    seed = f"AFE-DTE-{payment_id}-{receipt_data.get('reservation_id','')}"
    codigo_generacion = str(uuid.uuid5(uuid.NAMESPACE_DNS, seed)).upper()

    # Sello simulado
    sello_hash = hashlib.sha256(seed.encode()).hexdigest()[:40].upper()
    sello_recibido = f"{now.strftime('%Y')}{sello_hash}NZKZ"

    # Firma electrónica simulada (base64)
    firma_payload = json.dumps({"dte": payment_id, "ts": now.isoformat()}).encode()
    firma_electronica = base64.b64encode(firma_payload).decode()

    # --- Receptor ---
    receptor_name = (
        receipt_data.get("business_name")
        or receipt_data.get("customer")
        or "CLIENTE"
    ).upper()

    receptor = {
        "tipoDocumento": "36" if is_fiscal else "13",
        "numDocumento": receipt_data.get("nit") if is_fiscal else receipt_data.get("document_number", "00000000-0"),
        "nrc": receipt_data.get("nrc") if is_fiscal else None,
        "nombre": receptor_name,
        "codActividad": "55101" if is_fiscal else None,
        "descActividad": receipt_data.get("economic_activity") if is_fiscal else None,
        "direccion": {
            "departamento": "06",
            "municipio": "14",
            "complemento": receipt_data.get("customer_address", "EL SALVADOR")
        },
        "telefono": receipt_data.get("customer_phone", "0000-0000"),
        "correo": receipt_data.get("customer_email", "")
    }

    # --- Cuerpo del Documento ---
    items = []
    
    # Item 1: Hospedaje
    room_num = receipt_data.get("room_number", "---")
    res_id = receipt_data.get("reservation_id", "---")
    unit_price = base if is_fiscal else (base + iva)
    
    items.append({
        "numItem": 1,
        "tipoItem": 2,
        "numeroDocumento": None,
        "codigo": f"SRV-HOSP-{room_num}",
        "codTributo": None,
        "descripcion": f"SERVICIO DE HOSPEDAJE HABITACION #{room_num} - RESERVA {res_id}",
        "cantidad": 1.0,
        "uniMedida": 59,
        "precioUni": round(unit_price, 2),
        "montoDescu": 0,
        "ventaNoSuj": 0,
        "ventaExenta": 0,
        "ventaGravada": round(unit_price, 2),
        "tributos": ["20"] if is_fiscal else None,
        "psv": 0.0,
        "noGravado": 0.0,
        "ivaItem": round(iva, 6) if is_fiscal else 0
    })

    # Item 2: Impuesto de Turismo
    if tourism > 0.01:
        items.append({
            "numItem": 2,
            "tipoItem": 2,
            "numeroDocumento": None,
            "codigo": "IMP-TURISMO-5",
            "codTributo": "C8",
            "descripcion": "CONTRIBUCION ESPECIAL DE TURISMO (5%)",
            "cantidad": 1.0,
            "uniMedida": 59,
            "precioUni": round(tourism, 2),
            "montoDescu": 0,
            "ventaNoSuj": 0,
            "ventaExenta": 0,
            "ventaGravada": round(tourism, 2),
            "tributos": None,
            "psv": 0.0,
            "noGravado": 0.0,
            "ivaItem": 0
        })

    # --- Valor en Letras ---
    from app.services.pdf_service import numero_a_letras
    total_letras = numero_a_letras(amount_paid)

    # --- Tributos ---
    tributos = []
    if is_fiscal:
        tributos.append({
            "codigo": "20",
            "descripcion": "Impuesto al Valor Agregado 13%",
            "valor": round(iva, 2)
        })

    # --- Método de pago ---
    method_map = {
        "card": "02",
        "cash": "01",
        "transfer": "03",
    }
    method_code = method_map.get(receipt_data.get("method", ""), "99")

    # --- Estructura DTE Oficial ---
    dte = {
        "identificacion": {
            "version": 1,
            "ambiente": "01",
            "tipoDte": "01" if is_fiscal else "01",
            "numeroControl": f"DTE-01-S001P001-{payment_id.zfill(15)}",
            "codigoGeneracion": codigo_generacion,
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "tipoContingencia": None,
            "motivoContin": None,
            "fecEmi": now.strftime("%Y-%m-%d"),
            "horEmi": now.strftime("%H:%M:%S"),
            "tipoMoneda": "USD"
        },
        "documentoRelacionado": None,
        "emisor": {
            "nit": "06140101011011",
            "nrc": "1234567",
            "nombre": "AFE RESORT S.A. DE C.V.",
            "codActividad": "55101",
            "descActividad": "Servicios de alojamiento y turismo",
            "nombreComercial": "AFE Resort & Spa",
            "tipoEstablecimiento": "01",
            "direccion": {
                "departamento": "06",
                "municipio": "14",
                "complemento": "Final Av. La Revolución, Zona Costera, La Libertad, El Salvador"
            },
            "telefono": "22220000",
            "correo": "facturacionelectronica@aferesort.com",
            "codEstableMH": "S001",
            "codEstable": "S001",
            "codPuntoVentaMH": "P001",
            "codPuntoVenta": "P001"
        },
        "receptor": receptor,
        "otrosDocumentos": None,
        "ventaTercero": None,
        "cuerpoDocumento": items,
        "resumen": {
            "totalNoSuj": 0,
            "totalExenta": 0,
            "totalGravada": round(gravada + (tourism if tourism > 0.01 else 0), 2),
            "subTotalVentas": round(gravada + (tourism if tourism > 0.01 else 0), 2),
            "descuNoSuj": 0,
            "descuExenta": 0,
            "descuGravada": 0,
            "porcentajeDescuento": 0,
            "totalDescu": 0,
            "tributos": tributos if tributos else [],
            "subTotal": round(gravada + (tourism if tourism > 0.01 else 0), 2),
            "ivaRete1": 0,
            "reteRenta": 0,
            "montoTotalOperacion": round(amount_paid, 2),
            "totalNoGravado": 0.0,
            "totalPagar": round(amount_paid, 2),
            "totalLetras": total_letras,
            "totalIva": round(iva, 2) if is_fiscal else 0,
            "saldoFavor": 0.0,
            "condicionOperacion": 1,
            "pagos": [
                {
                    "codigo": method_code,
                    "montoPago": round(amount_paid, 2),
                    "referencia": f"PAY-{payment_id}",
                    "plazo": None,
                    "periodo": None
                }
            ],
            "numPagoElectronico": f"PE-{payment_id}" if method_code in ("02", "03") else None
        },
        "extension": {
            "nombEntrega": None,
            "docuEntrega": None,
            "nombRecibe": receptor_name,
            "docuRecibe": receptor.get("numDocumento"),
            "observaciones": f"Reserva {res_id} | Hab #{room_num} | {receipt_data.get('method', 'ONLINE').upper()}",
            "placaVehiculo": None
        },
        "apendice": [
            {
                "campo": "Reserva",
                "etiqueta": "ID Reservación",
                "valor": res_id
            },
            {
                "campo": "Habitacion",
                "etiqueta": "Número de Habitación",
                "valor": str(room_num)
            },
            {
                "campo": "CheckIn",
                "etiqueta": "Fecha Check-In",
                "valor": receipt_data.get("check_in", "---")
            },
            {
                "campo": "CheckOut",
                "etiqueta": "Fecha Check-Out",
                "valor": receipt_data.get("check_out", "---")
            }
        ],
        "firmaElectronica": firma_electronica,
        "selloRecibido": sello_recibido
    }

    return json.dumps(dte, indent=2, ensure_ascii=False).encode("utf-8")
