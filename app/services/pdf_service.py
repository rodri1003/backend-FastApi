import io
import qrcode
import random
from fpdf import FPDF
from datetime import datetime
from PIL import Image

def numero_a_letras(numero):
    unidades = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
    decenas = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
    diez_a_diecinueve = ["DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE"]
    veinte_a_veintinueve = ["VEINTE", "VEINTIUNO", "VEINTIDOS", "VEINTITRES", "VEINTICUATRO", "VEINTICINCO", "VEINTISEIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
    centenas_arr = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

    def convertir_grupo(n):
        if n == 100: return "CIEN"
        res = ""
        c = n // 100
        d = (n % 100) // 10
        u = n % 10
        if c > 0: res += centenas_arr[c] + " "
        if d == 1: res += diez_a_diecinueve[u]
        elif d == 2:
            res += "VEINTE" if u == 0 else veinte_a_veintinueve[u]
        elif d > 2:
            res += decenas[d]
            if u > 0: res += " Y " + unidades[u]
        else: res += unidades[u]
        return res.strip()

    enteros = int(numero)
    centavos = int(round((numero - enteros) * 100))
    if enteros == 0:
        letras = "CERO"
    else:
        millones = enteros // 1000000
        miles = (enteros % 1000000) // 1000
        uni = enteros % 1000
        letras = ""
        if millones > 0:
            letras += ("UN MILLON " if millones == 1 else convertir_grupo(millones) + " MILLONES ")
        if miles > 0:
            letras += ("MIL " if miles == 1 else convertir_grupo(miles) + " MIL ")
        if uni > 0:
            letras += convertir_grupo(uni)
    return f"{letras.strip()} {centavos:02d}/100 DÓLARES"


# =============================================================================
# CONSTANTES DE LAYOUT (todo calculado una sola vez)
# =============================================================================
LEFT = 15          # Margen izquierdo
RIGHT = 200        # Margen derecho (Letter = 215.9mm, 15mm margin)
TABLE_W = RIGHT - LEFT  # 185mm

# Anchos de columna de la tabla (DEBEN sumar 185)
COL_W = [10, 14, 16, 70, 20, 17, 17, 21]
# Posiciones X absolutas de cada columna
COL_X = []
_x = LEFT
for w in COL_W:
    COL_X.append(_x)
    _x += w

HEADERS = ["Nº", "Cant.", "Unidad", "Descripción", "P. Unit.", "No Suj.", "Exenta", "Gravada"]
HEADER_ALIGN = ['C', 'C', 'C', 'C', 'C', 'C', 'C', 'C']
DATA_ALIGN   = ['C', 'C', 'C', 'L', 'R', 'R', 'R', 'R']


def generate_receipt_pdf(receipt_data: dict) -> bytes:
    from app.db.session import SessionLocal
    from app.services.system_settings_service import get_setting

    hotel_name = "AFE Resort & Spa"
    hotel_phone = "2222-0000"
    hotel_email = "facturacionelectronica@aferesort.com"

    db = SessionLocal()
    try:
        hotel_name = get_setting(db, "hotel_name", "AFE Resort & Spa")
        hotel_phone = get_setting(db, "hotel_phone", "2222-0000")
        hotel_email = get_setting(db, "hotel_email", "facturacionelectronica@aferesort.com")
    except Exception:
        pass
    finally:
        db.close()

    # Formatear valores para emisor
    emisor_legal_name = f"{hotel_name.upper()} S.A. DE C.V." if "S.A." not in hotel_name.upper() else hotel_name.upper()
    
    # Generar iniciales para el logo
    hotelAbbr = 'AFE'
    if hotel_name != 'AFE Resort & Spa':
        words = [w for w in hotel_name.split() if len(w) > 2]
        if len(words) >= 2:
            hotelAbbr = "".join(w[0] for w in words).upper()[:4]
        else:
            hotelAbbr = hotel_name[:3].upper()

    pdf = FPDF(orientation='P', unit='mm', format='Letter')
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    # ---- helpers ----
    def trunc(txt, max_w, font='Helvetica', style='', size=8):
        """Truncate text with ellipsis if it exceeds max_w mm."""
        pdf.set_font(font, style, size)
        if pdf.get_string_width(txt) <= max_w:
            return txt
        while pdf.get_string_width(txt + '...') > max_w and len(txt) > 0:
            txt = txt[:-1]
        return txt.rstrip() + '...'

    def text_at(x, y, txt, font='Helvetica', style='', size=8, color=(0,0,0)):
        pdf.set_font(font, style, size)
        pdf.set_text_color(*color)
        pdf.text(x, y, txt)

    def cell_at(x, y, w, h, txt, border=1, align='C', font='Helvetica', style='', size=8, fill=False, color=None):
        pdf.set_xy(x, y)
        pdf.set_font(font, style, size)
        if color: pdf.set_text_color(*color)
        pdf.cell(w, h, txt, border, 0, align, fill)

    WHITE  = (255, 255, 255)
    BLACK  = (0, 0, 0)
    SLATE  = (71, 85, 105)
    GOLD   = (212, 175, 55)
    BORDER = (203, 213, 225)
    BG     = (248, 250, 252)
    DARK   = (30, 41, 59)  # Slate 800

    is_fiscal = receipt_data.get("receipt_type") == "fiscal_credit"
    title_dte = "CRÉDITO FISCAL" if is_fiscal else "CONSUMIDOR FINAL"
    payment_id = str(receipt_data.get("payment_id", random.randint(1000, 9999)))
    amount_paid = float(receipt_data.get("amount_paid", 0))
    total = amount_paid
    room_base = float(receipt_data.get("room_base", total / 1.18))
    room_iva = float(receipt_data.get("room_iva", room_base * 0.13))
    room_tourism = float(receipt_data.get("room_tourism", room_base * 0.05))
    extras_base = float(receipt_data.get("extras_base", 0))
    extras_iva = float(receipt_data.get("extras_iva", 0))
    incidentals_base = float(receipt_data.get("incidentals_base", 0))
    
    # Calculate incidentals_iva dynamically based on individual apply_tax properties
    incidentals_iva = 0.0
    for inc in receipt_data.get("incidentals", []):
        if inc.get("apply_tax", True):
            incidentals_iva += float(inc.get("amount", 0)) * float(inc.get("quantity", 1)) * 0.13

    base = room_base + extras_base + incidentals_base
    iva = room_iva + extras_iva + incidentals_iva
    tourism = room_tourism
    date_val = receipt_data.get("date", datetime.now().isoformat())[:19].replace('T', ' ')

    # =========================================================================
    # HEADER (y=15 .. y=48)
    # =========================================================================
    # Logo circle (centered text)
    logo_cx = LEFT + 15  # center x of circle
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.4)
    pdf.ellipse(LEFT, 15, 30, 30, 'D')
    pdf.set_font('Helvetica', 'B', 16)
    afe_w = pdf.get_string_width(hotelAbbr)
    text_at(logo_cx - afe_w/2, 32, hotelAbbr, style='B', size=16)
    pdf.set_font('Helvetica', '', 5)
    rs_w = pdf.get_string_width(hotel_name.upper()[:24])
    text_at(logo_cx - rs_w/2, 37, hotel_name.upper()[:24], size=5, color=SLATE)

    # Center title
    text_at(70, 24, "DOCUMENTO TRIBUTARIO ELECTRÓNICO", style='B', size=10)
    text_at(88, 30, title_dte, style='B', size=9, color=GOLD)

    # QR
    qr_data = f"DTE:{receipt_data.get('reservation_id')}|Total:${amount_paid}|ID:{payment_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    qr_img.save(buf, format='PNG')
    buf.seek(0)
    pdf.set_draw_color(*BLACK)
    pdf.set_line_width(0.2)
    pdf.image(buf, x=168, y=15, w=28, h=28)
    pdf.rect(168, 15, 28, 28, 'D')

    # =========================================================================
    # META INFO (y=50 .. y=62)
    # =========================================================================
    y = 50
    text_at(LEFT, y,   "Código de Generación:", style='B', size=7)
    text_at(50,   y,   f"4993AB40-5E45-47C0-8F41-{payment_id.zfill(12)}", size=7)
    text_at(130,  y,   "Modelo Facturación:", style='B', size=7)
    text_at(165,  y,   "Transmisión normal", size=7)

    y += 4
    text_at(LEFT, y,   "Número de Control:", style='B', size=7)
    text_at(50,   y,   f"DTE-01-S001P001-{payment_id.zfill(15)}", size=7)
    text_at(130,  y,   "Tipo Transmisión:", style='B', size=7)
    text_at(165,  y,   "Normal", size=7)

    y += 4
    text_at(LEFT, y,   "Sello de Recepción:", style='B', size=7)
    text_at(50,   y,   "2026A6F5AE42BD8642B79FB8E598599430DCNZKZ", size=7)
    text_at(130,  y,   "Fecha y Hora:", style='B', size=7)
    text_at(165,  y,   date_val, size=7)

    # =========================================================================
    # EMISOR / RECEPTOR BOXES (modern dark-header style)
    # =========================================================================
    box_y = 66
    hdr_h = 7
    body_h = 28
    box_w = 90
    gap = 5
    rx = LEFT + box_w + gap

    def info_box(bx, by, w, title, lines_data):
        # Dark header bar
        pdf.set_fill_color(*DARK)
        pdf.set_draw_color(*DARK)
        cell_at(bx, by, w, hdr_h, title, border=1, align='C', style='B', size=7, fill=True, color=WHITE)
        # Body with light border
        pdf.set_draw_color(*BORDER)
        pdf.rect(bx, by + hdr_h, w, body_h, 'D')
        # Content (with safe truncation)
        ly = by + hdr_h + 2
        max_val_w = w - 6  # padding
        for lbl, val in lines_data:
            pdf.set_font('Helvetica', 'B', 6.5)
            lbl_w = pdf.get_string_width(lbl) + 1
            safe_val = trunc(val, max_val_w - lbl_w, size=6.5)
            text_at(bx + 3, ly + 3, lbl, style='B', size=6.5)
            text_at(bx + 3 + lbl_w, ly + 3, safe_val, size=6.5, color=SLATE)
            ly += 4

    info_box(LEFT, box_y, box_w, 'EMISOR', [
        ('Nombre:', emisor_legal_name),
        ('Correo:', hotel_email),
        ('Dirección:', 'Final Av. La Revolución, El Salvador'),
        ('Teléfono:', hotel_phone),
        ('NIT:', '0614-010101-101-1    NRC: 123456-7'),
        ('Giro:', 'SERVICIOS DE ALOJAMIENTO'),
    ])

    receptor_name = (receipt_data.get('business_name') or receipt_data.get('customer') or 'CLIENTE').upper()
    receptor_lines = [
        ('Nombre:', receptor_name),
        ('Correo:', receipt_data.get('customer_email') or '---'),
        ('Dirección:', receipt_data.get('customer_address') or 'EL SALVADOR'),
        ('Teléfono:', receipt_data.get('customer_phone') or '---'),
    ]
    if is_fiscal:
        receptor_lines.append(('NIT:', f"{receipt_data.get('nit','---')}    NRC: {receipt_data.get('nrc','---')}"))
        receptor_lines.append(('Giro:', (receipt_data.get('economic_activity') or '---')[:35]))
    else:
        receptor_lines.append(('DUI/Doc:', receipt_data.get('document_number', '---')))
    info_box(rx, box_y, box_w, 'RECEPTOR', receptor_lines)

    # =========================================================================
    # PRODUCT TABLE (y=106 .. ~y=175)
    # =========================================================================
    table_y = box_y + hdr_h + body_h + 6   # Start of table header
    row_h = 8

    # ---- Table Header ----
    pdf.set_fill_color(*DARK)
    pdf.set_draw_color(*DARK)
    for i in range(len(HEADERS)):
        cell_at(COL_X[i], table_y, COL_W[i], row_h, HEADERS[i],
                border=1, align=HEADER_ALIGN[i], style='B', size=7, fill=True, color=WHITE)
    # Gold accent line under header
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.6)
    pdf.line(LEFT, table_y + row_h, RIGHT, table_y + row_h)
    pdf.set_line_width(0.2)

    # ---- Data Rows: Itemized & Dynamic ----
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
                "name": f"Hospedaje Hab #{room_num} - {res_id}",
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
                "name": f"Amenidad: {ex.get('name', 'Amenidad')}",
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
                "name": f"Incidental: {inc.get('description', 'Cargo')}",
                "quantity": qty,
                "unit_price": float(inc.get("amount", 0)),
                "apply_tax": inc.get("apply_tax", True),
                "total_amount": total_net,
                "tax": tax_val,
                "tourism": 0.0,
                "total": total_net + tax_val
            })

    next_y = table_y + row_h
    row_count = 1
    pdf.set_draw_color(*BORDER)
    pdf.set_font('Helvetica', '', 7)

    for item in allocated_items:
        apply_tax = item.get("apply_tax", True)
        cov_total_net = float(item["total_amount"])
        cov_tax = float(item["tax"])
        
        qty = float(item["quantity"])
        unit_net = float(item["unit_price"])
        
        if not is_fiscal and apply_tax:
            u_price = unit_net * (1.0 + iva_rate)
        else:
            u_price = unit_net
            
        tot_row_val = u_price * qty
        
        pdf.set_fill_color(255, 255, 255)
        row_cols = [
            str(row_count), f"{qty:.2f}", "Servicio",
            trunc(item["name"], COL_W[3] - 2, size=7),
            f"${u_price:,.2f}", "$0.00", "$0.00", f"${tot_row_val:,.2f}"
        ]
        for i, val in enumerate(row_cols):
            cell_at(COL_X[i], next_y, COL_W[i], row_h, val,
                    border=1, align=DATA_ALIGN[i], size=7, color=BLACK)
        next_y += row_h
        row_count += 1

    # ---- Data Row: Turismo ----
    if tourism > 0:
        pdf.set_fill_color(*BG)
        row2 = [
            str(row_count), "1.00", "Impuesto", "Impuesto de Turismo (5%)",
            f"${tourism:,.2f}", "$0.00", "$0.00", f"${tourism:,.2f}"
        ]
        for i, val in enumerate(row2):
            cell_at(COL_X[i], next_y, COL_W[i], row_h, val,
                    border=1, align=DATA_ALIGN[i], size=7, fill=True, color=BLACK)
        next_y += row_h

    # ---- Empty filler rows (to reach a fixed bottom) ----
    table_bottom = 178
    if next_y < table_bottom:
        filler_h = table_bottom - next_y
        for i in range(len(COL_W)):
            cell_at(COL_X[i], next_y, COL_W[i], filler_h, "", border=1, size=7)

    # =========================================================================
    # TOTALS (fused directly under table, right-aligned with last columns)
    # =========================================================================
    tot_x = COL_X[4]
    tot_w_label = COL_W[4] + COL_W[5] + COL_W[6]  # 54mm
    tot_w_val = COL_W[7]  # 21mm
    ty = table_bottom  # NO gap — directly under table

    pdf.set_draw_color(*BORDER)

    def totals_row(label, value, bold=False, accent=False):
        nonlocal ty
        c = GOLD if accent else BLACK
        s = 9 if accent else 7
        st = 'B' if (bold or accent) else ''
        cell_at(tot_x, ty, tot_w_label, 6, label, border='LRB', align='R', style=st, size=s, color=c)
        cell_at(tot_x + tot_w_label, ty, tot_w_val, 6, f"${value:,.2f}", border='RB', align='R', style=st, size=s, color=c)
        ty += 6

    if is_fiscal:
        totals_row('Suma de Ventas:', base)
        totals_row('IVA 13%:', iva, bold=True)
        totals_row('Sub-Total:', base + iva, bold=True)
    else:
        totals_row('Ventas Gravadas:', base + iva)
        totals_row('Sub-Total:', base + iva)

    if tourism > 0:
        totals_row('Imp. Turismo (5%):', tourism, bold=True)

    totals_row('IVA Retenido:', 0)
    totals_row('Monto Total Operación:', total, bold=True)
    # Final row with gold background
    pdf.set_fill_color(*GOLD)
    cell_at(tot_x, ty, tot_w_label, 8, 'TOTAL A PAGAR:', border=1, align='R', style='B', size=10, fill=True, color=WHITE)
    cell_at(tot_x + tot_w_label, ty, tot_w_val, 8, f'${total:,.2f}', border=1, align='R', style='B', size=10, fill=True, color=WHITE)

    # =========================================================================
    # OBSERVACIONES (compact, below totals with gap)
    # =========================================================================
    totals_end_y = ty + 8  # bottom of gold TOTAL row
    obs_y = totals_end_y + 6
    obs_w = TABLE_W
    obs_body_h = 18  # compact

    pdf.set_fill_color(*DARK)
    pdf.set_draw_color(*DARK)
    cell_at(LEFT, obs_y, obs_w, hdr_h, 'OBSERVACIONES', border=1, align='C', style='B', size=7, fill=True, color=WHITE)
    pdf.set_draw_color(*BORDER)
    pdf.rect(LEFT, obs_y + hdr_h, obs_w, obs_body_h, 'D')

    oy = obs_y + hdr_h + 3
    letras_txt = trunc(numero_a_letras(total), obs_w * 1.5, size=7)  # generous limit
    text_at(LEFT + 3, oy + 1, 'Son:', style='B', size=7)
    text_at(LEFT + 13, oy + 1, letras_txt, size=7, color=SLATE)
    oy += 5
    text_at(LEFT + 3, oy + 1, 'Condición: CONTADO', style='B', size=7)
    text_at(LEFT + 50, oy + 1, f"Método: {receipt_data.get('method','ONLINE').upper()}", size=7, color=SLATE)
    text_at(LEFT + 100, oy + 1, f"Ref: {payment_id}", size=7, color=SLATE)
    text_at(LEFT + 130, oy + 1, f"Aut: {random.randint(100000,999999)}", size=7, color=SLATE)

    # =========================================================================
    # FOOTER (dynamic y based on content above)
    # =========================================================================
    footer_y = obs_y + hdr_h + obs_body_h + 8  # always below obs box
    footer_y = max(footer_y, 250)  # but never above 250mm

    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.4)
    pdf.line(LEFT, footer_y, RIGHT, footer_y)

    text_at(LEFT, footer_y + 4, f'Responsable: {emisor_legal_name}', style='B', size=7, color=SLATE)
    text_at(RIGHT - 45, footer_y + 4, f'N\u00ba Documento: {payment_id}', style='B', size=7, color=SLATE)

    pdf.set_font('Helvetica', 'B', 7)
    pag_w = pdf.get_string_width('P\u00e1gina 1 de 1')
    pag_x = LEFT + (TABLE_W - pag_w) / 2
    text_at(pag_x, footer_y + 9, 'P\u00e1gina 1 de 1', style='B', size=7, color=SLATE)

    return pdf.output()
