"""
Genera el PDF de un presupuesto (cotización) de Mezclilla San Miguel:
logo, datos fiscales, cliente, tabla de productos con precio en divisa
y en bolívares, totales, tasa BCV usada y condiciones.
"""

import os
import sys
from datetime import datetime, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER


def _base_dir():
    """Carpeta del .exe cuando está empaquetado (PyInstaller --onefile),
    o del script cuando corre desde código fuente. Ver la misma función
    en app.py para el porqué: __file__ solo no sirve en modo --onefile
    porque apunta a una carpeta temporal que se borra al cerrar la app."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
LOGO_PATH = os.path.join(BASE_DIR, "resources", "logo.png")

NOMBRE_NEGOCIO = "Mezclilla San Miguel C.A"
RIF_NEGOCIO = "J-30659613-5"


def _fmt_usd(v):
    return f"$ {v:,.2f}"


def _fmt_bs(v):
    return f"Bs {v:,.2f}"


def generar_pdf(path, presupuesto):
    """
    presupuesto: dict con
        numero (int), fecha (datetime), validez_dias (int),
        cliente_nombre (str), cliente_telefono (str),
        items (list of dict: producto, cantidad, precio_unit_divisa,
               precio_unit_bs, subtotal_divisa, subtotal_bs),
        total_divisa (float), total_bs (float),
        tasa_bcv (float), tasa_fuente (str),
        nota (str)
    """
    styles = getSampleStyleSheet()
    estilo_normal = styles["Normal"]
    estilo_titulo = ParagraphStyle(
        "TituloPresupuesto", parent=styles["Title"], fontSize=18, spaceAfter=0,
        textColor=colors.HexColor("#1a237e"),
    )
    estilo_empresa = ParagraphStyle(
        "Empresa", parent=styles["Normal"], fontSize=14, leading=17,
        fontName="Helvetica-Bold",
    )
    estilo_dato = ParagraphStyle("Dato", parent=styles["Normal"], fontSize=9.5, leading=13)
    estilo_derecha = ParagraphStyle("Derecha", parent=estilo_dato, alignment=TA_RIGHT)
    estilo_centro_chico = ParagraphStyle("CentroChico", parent=estilo_dato, alignment=TA_CENTER,
                                          fontSize=8, textColor=colors.HexColor("#555555"))
    estilo_nota = ParagraphStyle("Nota", parent=estilo_dato, fontSize=8.5,
                                  textColor=colors.HexColor("#444444"), leading=12)

    doc = SimpleDocTemplate(
        path, pagesize=letter,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=f"Presupuesto {presupuesto['numero']:04d} - {NOMBRE_NEGOCIO}",
    )

    elementos = []

    # --- Encabezado: logo + datos del negocio a la izquierda, datos del
    # presupuesto (número/fecha/validez) a la derecha.
    fecha = presupuesto["fecha"]
    vence = fecha + timedelta(days=presupuesto["validez_dias"])

    bloque_izq = []
    if os.path.exists(LOGO_PATH):
        bloque_izq.append(Image(LOGO_PATH, width=1.6 * cm, height=1.6 * cm))
    bloque_izq_tabla = Table(
        [[bloque_izq[0] if bloque_izq else "", Paragraph(
            f"{NOMBRE_NEGOCIO}<br/>RIF: {RIF_NEGOCIO}", estilo_empresa)]],
        colWidths=[1.9 * cm, 9 * cm],
    )
    bloque_izq_tabla.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))

    bloque_der = Table(
        [
            [Paragraph("<b>PRESUPUESTO</b>", estilo_titulo)],
            [Paragraph(f"N° {presupuesto['numero']:04d}", estilo_derecha)],
            [Paragraph(f"Fecha: {fecha.strftime('%d/%m/%Y')}", estilo_derecha)],
            [Paragraph(f"Válido hasta: {vence.strftime('%d/%m/%Y')}", estilo_derecha)],
        ],
        colWidths=[6.5 * cm],
    )
    bloque_der.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    encabezado = Table(
        [[bloque_izq_tabla, bloque_der]],
        colWidths=[11 * cm, 6.5 * cm],
    )
    encabezado.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elementos.append(encabezado)
    elementos.append(Spacer(1, 8))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a237e")))
    elementos.append(Spacer(1, 10))

    # --- Datos del cliente
    cliente_nombre = presupuesto.get("cliente_nombre") or "—"
    cliente_telefono = presupuesto.get("cliente_telefono") or "—"
    tabla_cliente = Table(
        [[Paragraph(f"<b>Cliente:</b> {cliente_nombre}", estilo_dato),
          Paragraph(f"<b>Teléfono:</b> {cliente_telefono}", estilo_dato)]],
        colWidths=[9 * cm, 8.5 * cm],
    )
    tabla_cliente.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    elementos.append(tabla_cliente)
    elementos.append(Spacer(1, 14))

    # --- Tabla de productos (solo precios base en dólares — ver condiciones
    # sobre por qué no se incluye una columna en bolívares: esos precios
    # están sujetos a cambios y la tasa BCV varía día a día).
    encabezados = ["Cant.", "Descripción", "Precio US$", "Subtotal US$"]
    filas = [encabezados]
    for it in presupuesto["items"]:
        filas.append([
            f"{it['cantidad']:g}",
            it["producto"],
            _fmt_usd(it["precio_unit_divisa"]),
            _fmt_usd(it["subtotal_divisa"]),
        ])

    tabla_items = Table(filas, colWidths=[1.8 * cm, 8.2 * cm, 3.5 * cm, 3.5 * cm],
                         repeatRows=1)
    tabla_items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f3f8")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9cbe0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elementos.append(tabla_items)
    elementos.append(Spacer(1, 12))

    # --- Total (solo en divisa; ver condiciones para el equivalente en Bs)
    tabla_totales = Table(
        [["", "Total en divisa:", _fmt_usd(presupuesto["total_divisa"])]],
        colWidths=[9.9 * cm, 4 * cm, 3.1 * cm],
    )
    tabla_totales.setStyle(TableStyle([
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (1, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (1, 0), (-1, -1), 10.5),
        ("LINEABOVE", (1, 0), (-1, 0), 0.8, colors.HexColor("#1a237e")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementos.append(tabla_totales)
    elementos.append(Spacer(1, 18))

    # --- Nota / condiciones
    nota = presupuesto.get("nota") or ""
    tasa = presupuesto["tasa_bcv"]
    condiciones = (
        "Los precios de este presupuesto están expresados en dólares (US$) y están sujetos "
        "a cambios sin previo aviso. Si el pago se realiza en bolívares, el monto se "
        f"convertirá a la tasa BCV vigente el día del pago (tasa de referencia al emitir "
        f"este presupuesto: {tasa:,.2f} Bs/US$, fuente: {presupuesto.get('tasa_fuente') or '—'}). "
        f"Este presupuesto tiene una validez de {presupuesto['validez_dias']} día(s) desde su "
        "fecha de emisión."
    )
    elementos.append(Paragraph(f"<b>Condiciones:</b> {condiciones}", estilo_nota))
    if nota.strip():
        elementos.append(Spacer(1, 6))
        elementos.append(Paragraph(f"<b>Nota adicional:</b> {nota.strip()}", estilo_nota))

    elementos.append(Spacer(1, 24))
    elementos.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#c9cbe0")))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph(
        f"{NOMBRE_NEGOCIO} — RIF {RIF_NEGOCIO} · Generado el "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}",
        estilo_centro_chico))

    doc.build(elementos)
    return path
