from decimal import Decimal
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models.reservation import Reservation
from app.services.system_settings_service import get_tax_iva, get_tax_tourism

def allocate_payment_items(db: Session, reservation: Reservation, payment_amount: Decimal) -> List[Dict[str, Any]]:
    """
    Distribuye proporcionalmente el monto de un pago entre los conceptos cobrados
    en la reservación (Alojamiento, Extras e Incidentales) en orden de prioridad contable:
    1. Alojamiento (Habitación + IVA + Turismo)
    2. Servicios Extras (Amenidades contratadas + IVA)
    3. Cargos Incidentales (Cargos manuales ad-hoc + IVA si aplica)
    
    Retorna una lista plana de ítems cubiertos por esta transacción, la cual suma exactamente
    el monto pagado, evitando descuadres contables y cumpliendo con el Ministerio de Hacienda.
    """
    iva_rate = Decimal(str(get_tax_iva(db)))
    tourism_rate = Decimal(str(get_tax_tourism(db)))
    
    # 1. Calcular el total acumulado previamente pagado (pagos 'completed')
    completed_payments_total = Decimal('0.00')
    if reservation.payments:
        for p in reservation.payments:
            if p.status == "completed":
                completed_payments_total += Decimal(str(p.amount))
                
    new_payment_amount = Decimal(str(payment_amount))
    total_allocated_limit = completed_payments_total + new_payment_amount
    
    # 2. Compilar el desglose completo del folio general en orden de prioridad
    all_items = []
    
    # Concepto 1: Alojamiento (Habitación + IVA + Turismo)
    room_subtotal = Decimal(str(reservation.subtotal or 0))
    room_iva = Decimal(str(reservation.tax_iva or 0))
    room_tourism = Decimal(str(reservation.tax_tourism or 0))
    room_gross = Decimal(str(reservation.total_cost or 0))
    
    if room_gross > 0:
        all_items.append({
            "type": "room",
            "code": f"SRV-HOSP-{reservation.room.number}",
            "description": f"Servicio de Alojamiento (Hab #{reservation.room.number})",
            "quantity": Decimal('1.00'),
            "net_unit": room_subtotal,
            "iva_unit": room_iva,
            "tourism_unit": room_tourism,
            "gross_total": room_gross,
            "apply_tax": True,
            "is_tourism": True
        })
        
    # Concepto 2: Extras
    if reservation.extras:
        for ex in reservation.extras:
            ex_qty = Decimal(str(ex.quantity))
            ex_net_unit = Decimal(str(ex.unit_price))
            ex_iva_unit = ex_net_unit * iva_rate
            ex_gross_unit = ex_net_unit + ex_iva_unit
            ex_gross_total = ex_gross_unit * ex_qty
            
            if ex_gross_total > 0:
                all_items.append({
                    "type": "extra",
                    "code": f"SRV-EXTRA-{ex.id}",
                    "description": f"Amenidad Extra: {ex.extra_amenity.name.upper()}",
                    "quantity": ex_qty,
                    "net_unit": ex_net_unit,
                    "iva_unit": ex_iva_unit,
                    "tourism_unit": Decimal('0.00'),
                    "gross_total": ex_gross_total,
                    "apply_tax": True,
                    "is_tourism": False
                })
                
    # Concepto 3: Incidentales
    if hasattr(reservation, 'incidental_charges') and reservation.incidental_charges:
        for ch in reservation.incidental_charges:
            if ch.payment_status != "waived" and not getattr(ch, 'is_deleted', False):
                inc_qty = Decimal(str(ch.quantity))
                inc_net_unit = Decimal(str(ch.amount))
                inc_iva_unit = inc_net_unit * iva_rate if ch.apply_tax else Decimal('0.00')
                inc_gross_unit = inc_net_unit + inc_iva_unit
                inc_gross_total = inc_gross_unit * inc_qty
                
                if inc_gross_total > 0:
                    all_items.append({
                        "type": "incidental",
                        "code": f"SRV-INC-{ch.id}",
                        "description": f"Cargo Incidental: {ch.description.upper()}",
                        "quantity": inc_qty,
                        "net_unit": inc_net_unit,
                        "iva_unit": inc_iva_unit,
                        "tourism_unit": Decimal('0.00'),
                        "gross_total": inc_gross_total,
                        "apply_tax": ch.apply_tax,
                        "is_tourism": False
                    })
                    
    # 3. Simular la imputación y encontrar la intersección del pago actual
    allocated_so_far = Decimal('0.00')
    current_payment_allocated = Decimal('0.00')
    covered_items = []
    
    for item in all_items:
        item_gross = item["gross_total"]
        item_start = allocated_so_far
        item_end = allocated_so_far + item_gross
        
        intersect_start = max(completed_payments_total, item_start)
        intersect_end = min(total_allocated_limit, item_end)
        
        if intersect_start < intersect_end:
            # Este ítem recibe fondos de la transacción actual
            covered_gross = intersect_end - intersect_start
            fraction = covered_gross / item_gross
            
            cov_qty = float(item["quantity"] * fraction)
            cov_net = float(item["net_unit"] * item["quantity"] * fraction)
            cov_iva = float(item["iva_unit"] * item["quantity"] * fraction)
            cov_tourism = float(item["tourism_unit"] * item["quantity"] * fraction)
            
            # Nombre/descripción con indicador de pago parcial si es necesario
            display_name = item["description"]
            if fraction < Decimal('0.99') and item["type"] == "room":
                display_name += " (Abono Proporcional)"
            elif fraction < Decimal('0.99'):
                display_name += " (Pago Parcial)"
                
            covered_items.append({
                "type": item["type"],
                "code": item["code"],
                "name": display_name,
                "quantity": round(cov_qty, 2),
                "unit_price": float(item["net_unit"]),
                "amount": float(item["net_unit"]),
                "apply_tax": item["apply_tax"],
                "total_amount": round(cov_net, 2),
                "tax": round(cov_iva, 2),
                "tourism": round(cov_tourism, 2),
                "total": round(float(covered_gross), 2)
            })
            current_payment_allocated += covered_gross
            
        allocated_so_far = item_end
        if allocated_so_far >= total_allocated_limit:
            break
            
    # Ajuste de desborde/seguridad: si la suma da menos por decimales o pago excede grand total
    if current_payment_allocated < new_payment_amount:
        remaining = new_payment_amount - current_payment_allocated
        if covered_items:
            # Asignar la diferencia al último ítem procesado
            last = covered_items[-1]
            last["total"] = round(last["total"] + float(remaining), 2)
            if last["apply_tax"]:
                add_net = remaining / (Decimal('1.00') + iva_rate)
                add_iva = remaining - add_net
                last["total_amount"] = round(last["total_amount"] + float(add_net), 2)
                last["tax"] = round(last["tax"] + float(add_iva), 2)
            else:
                last["total_amount"] = round(last["total_amount"] + float(remaining), 2)
        else:
            # Crear ítem genérico de seguridad
            covered_items.append({
                "type": "room",
                "code": "SRV-HOSP-ADJ",
                "name": "Servicio de Alojamiento (Abono)",
                "quantity": 1.0,
                "unit_price": float(remaining / (Decimal('1.00') + iva_rate)),
                "amount": float(remaining / (Decimal('1.00') + iva_rate)),
                "apply_tax": True,
                "total_amount": round(float(remaining / (Decimal('1.00') + iva_rate)), 2),
                "tax": round(float(remaining - (remaining / (Decimal('1.00') + iva_rate))), 2),
                "tourism": 0.0,
                "total": round(float(remaining), 2)
            })
            
    return covered_items
