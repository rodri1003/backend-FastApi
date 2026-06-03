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
    from app.db.session import SessionLocal
    from app.services.system_settings_service import get_setting

    hotel_name = "AFE Resort & Spa"
    hotel_phone = "22220000"
    hotel_email = "facturacionelectronica@aferesort.com"

    db = SessionLocal()
    try:
        hotel_name = get_setting(db, "hotel_name", "AFE Resort & Spa")
        hotel_phone = get_setting(db, "hotel_phone", "22220000")
        hotel_email = get_setting(db, "hotel_email", "facturacionelectronica@aferesort.com")
    except Exception:
        pass
    finally:
        db.close()

    # Formatear valores para emisor
    emisor_legal_name = f"{hotel_name.upper()} S.A. DE C.V." if "S.A." not in hotel_name.upper() else hotel_name.upper()
    emisor_phone_digits = "".join(filter(str.isdigit, hotel_phone)) if hotel_phone else "22220000"
    if not emisor_phone_digits:
        emisor_phone_digits = "22220000"

    now = datetime.now()
    payment_id = str(receipt_data.get("payment_id", random.randint(1000, 9999)))
    is_fiscal = receipt_data.get("receipt_type") == "fiscal_credit"
    amount_paid = float(receipt_data.get("amount_paid", 0))

    # Cálculos fiscales usando desglose del receipt_data
    room_base = float(receipt_data.get("room_base", amount_paid / 1.18))
    room_iva = float(receipt_data.get("room_iva", room_base * 0.13))
    room_tourism = float(receipt_data.get("room_tourism", room_base * 0.05))
    extras_base = float(receipt_data.get("extras_base", 0))
    extras_iva = float(receipt_data.get("extras_iva", 0))
    incidentals_base = float(receipt_data.get("incidentals_base", 0))
    incidentals_iva = float(receipt_data.get("incidentals_iva", 0))
    
    base = room_base + extras_base + incidentals_base
    iva = room_iva + extras_iva + incidentals_iva
    tourism = room_tourism
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
    
    allocated_items = receipt_data.get("items", [])
    iva_rate = float(receipt_data.get("tax_iva_rate", 0.13))
    room_num = receipt_data.get("room_number", "---")
    res_id = receipt_data.get("reservation_id", "---")

    if not allocated_items:
        # Reconstrucción defensiva para recibos históricos (Legacy Fallback)
        allocated_items = []
        if room_base > 0.01:
            allocated_items.append({
                "type": "room",
                "code": f"SRV-HOSP-{room_num}",
                "name": f"Servicio de Alojamiento (Hab #{room_num}) - Reserva {res_id}",
                "quantity": 1.0,
                "unit_price": room_base,
                "apply_tax": True,
                "total_amount": room_base,
                "tax": room_iva,
                "tourism": room_tourism,
                "total": room_base + room_iva + room_tourism
            })
        for i, ex in enumerate(receipt_data.get("extras", [])):
            qty = float(ex.get("quantity", 1))
            total_net = float(ex.get("total_price", ex.get("unit_price", 0) * qty))
            tax_val = total_net * iva_rate
            allocated_items.append({
                "type": "extra",
                "code": f"SRV-EXTRA-{i+1}",
                "name": f"AMENIDAD EXTRA: {ex.get('name', 'Amenidad').upper()}",
                "quantity": qty,
                "unit_price": float(ex.get("unit_price", 0)),
                "apply_tax": True,
                "total_amount": total_net,
                "tax": tax_val,
                "tourism": 0.0,
                "total": total_net + tax_val
            })
        for i, inc in enumerate(receipt_data.get("incidentals", [])):
            qty = float(inc.get("quantity", 1))
            total_net = float(inc.get("total_amount", inc.get("amount", 0) * qty))
            tax_val = total_net * iva_rate if inc.get("apply_tax", True) else 0.0
            allocated_items.append({
                "type": "incidental",
                "code": f"SRV-INC-{i+1}",
                "name": f"CARGO INCIDENTAL: {inc.get('description', 'Cargo').upper()}",
                "quantity": qty,
                "unit_price": float(inc.get("amount", 0)),
                "apply_tax": inc.get("apply_tax", True),
                "total_amount": total_net,
                "tax": tax_val,
                "tourism": 0.0,
                "total": total_net + tax_val
            })

    item_num = 1
    for item in allocated_items:
        apply_tax = item.get("apply_tax", True)
        cov_total_net = float(item["total_amount"])
        cov_tax = float(item["tax"])
        cov_tourism = float(item.get("tourism", 0.0))
        
        qty = float(item["quantity"])
        if qty <= 0:
            qty = 1.0
            
        unit_net = float(item["unit_price"])
        if not is_fiscal and apply_tax:
            unit_display = unit_net * (1.0 + iva_rate)
        else:
            unit_display = unit_net
            
        # Venta gravada vs exenta
        # Para consumidor final la venta gravada debe incluir el IVA
        v_gravada = round(cov_total_net + cov_tax, 2) if (not is_fiscal and apply_tax) else (round(cov_total_net, 2) if apply_tax else 0.0)
        v_exenta = 0.0 if apply_tax else round(cov_total_net, 2)
        
        items.append({
            "numItem": item_num,
            "tipoItem": 2,
            "numeroDocumento": None,
            "codigo": item["code"],
            "codTributo": None,
            "descripcion": item["name"].upper(),
            "quantity": qty,
            "cantidad": qty,
            "uniMedida": 59,
            "precioUni": round(unit_display, 2),
            "montoDescu": 0,
            "ventaNoSuj": 0,
            "ventaExenta": v_exenta,
            "ventaGravada": v_gravada,
            "tributos": ["20"] if (is_fiscal and apply_tax) else None,
            "psv": 0.0,
            "noGravado": 0.0,
            "ivaItem": round(cov_tax, 6) if (is_fiscal and apply_tax) else 0
        })
        item_num += 1

    # Agregar contribución de turismo de forma unificada si está presente en el desglose
    # y es mayor a 0
    if tourism > 0.01:
        items.append({
            "numItem": item_num,
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
            "nombre": emisor_legal_name,
            "codActividad": "55101",
            "descActividad": "Servicios de alojamiento y turismo",
            "nombreComercial": hotel_name,
            "tipoEstablecimiento": "01",
            "direccion": {
                "departamento": "06",
                "municipio": "14",
                "complemento": "Final Av. La Revolución, Zona Costera, La Libertad, El Salvador"
            },
            "telefono": emisor_phone_digits,
            "correo": hotel_email,
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
