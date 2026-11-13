"""
Convierte un documento Markdown sencillo (títulos, párrafos, listas, tablas, enlaces) en un PDF A4.
Lo usan los documentos de la solicitud a Meta (docs/*.md -> docs/*.pdf).

Requiere:  pip install reportlab
Uso:  python beta/guia/md2pdf.py entrada.md salida.pdf ["Título del encabezado"]
"""
import math
import os
import re
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

FUENTES = "C:/Windows/Fonts"
try:
    pdfmetrics.registerFont(TTFont("Cal", os.path.join(FUENTES, "calibri.ttf")))
    pdfmetrics.registerFont(TTFont("Cal-B", os.path.join(FUENTES, "calibrib.ttf")))
    pdfmetrics.registerFont(TTFont("Cal-I", os.path.join(FUENTES, "calibrii.ttf")))
    pdfmetrics.registerFont(TTFont("Cal-BI", os.path.join(FUENTES, "calibriz.ttf")))
    pdfmetrics.registerFont(TTFont("Mono", os.path.join(FUENTES, "consola.ttf")))
    pdfmetrics.registerFontFamily("Cal", normal="Cal", bold="Cal-B", italic="Cal-I", boldItalic="Cal-BI")
    F, FB, FM = "Cal", "Cal-B", "Mono"
except Exception:  # noqa: BLE001
    F, FB, FM = "Helvetica", "Helvetica-Bold", "Courier"

NAVY, ACENTO, GRIS = colors.HexColor("#14213d"), colors.HexColor("#4f46e5"), colors.HexColor("#475569")
EST = {
    "p": ParagraphStyle("p", fontName=F, fontSize=10.5, leading=15, textColor=colors.HexColor("#1e293b"), spaceAfter=6),
    "h1": ParagraphStyle("h1", fontName=FB, fontSize=21, leading=26, textColor=NAVY, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName=FB, fontSize=14.5, leading=19, textColor=ACENTO, spaceBefore=12, spaceAfter=5),
    "h3": ParagraphStyle("h3", fontName=FB, fontSize=12, leading=16, textColor=NAVY, spaceBefore=8, spaceAfter=3),
    "celda": ParagraphStyle("celda", fontName=F, fontSize=9.5, leading=12.5, textColor=colors.HexColor("#1e293b")),
    "celdah": ParagraphStyle("celdah", fontName=FB, fontSize=9.5, leading=12.5, textColor=NAVY),
    "meta": ParagraphStyle("meta", fontName=F, fontSize=10, leading=13, textColor=GRIS, spaceAfter=10),
}


def inline(t: str) -> str:
    """Markdown en línea -> marcado de reportlab."""
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\\([\[\]()*_`])", lambda m: {"[": "\x01", "]": "\x02", "(": "\x03", ")": "\x04", "*": "\x05", "_": "\x06", "`": "\x07"}[m.group(1)], t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<link href="{m.group(2)}" color="#4f46e5"><u>{m.group(1)}</u></link>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", rf'<font face="{FM}">\1</font>', t)
    for k, v in {"\x01": "[", "\x02": "]", "\x03": "(", "\x04": ")", "\x05": "*", "\x06": "_", "\x07": "`"}.items():
        t = t.replace(k, v)
    return t


def pesos_columnas(filas):
    n = len(filas[0])
    pesos = []
    for c in range(n):
        largo = sum(len(re.sub(r"\W", "", f[c])) for f in filas) / len(filas)
        pesos.append(max(4.0, min(60.0, largo)) ** 0.7)
    s = sum(pesos)
    return [p / s for p in pesos]


def tabla(filas, ancho):
    datos = [[Paragraph(inline(c), EST["celdah" if i == 0 else "celda"]) for c in fila] for i, fila in enumerate(filas)]
    t = Table(datos, colWidths=[ancho * p for p in pesos_columnas(filas)], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef0fb")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def construir(md: str, ancho: float):
    flujo, lineas, i = [], md.split("\n"), 0
    while i < len(lineas):
        ln = lineas[i].rstrip()
        if not ln.strip():
            i += 1
        elif ln.startswith("### "):
            flujo.append(Paragraph(inline(ln[4:]), EST["h3"])); i += 1
        elif ln.startswith("## "):
            flujo.append(Paragraph(inline(ln[3:]), EST["h2"])); i += 1
        elif ln.startswith("# "):
            flujo.append(Paragraph(inline(ln[2:]), EST["h1"])); i += 1
            if i < len(lineas) and lineas[i].strip() and not lineas[i].startswith(("#", "|", "-", "1.")) and re.search(r"\d{4}", lineas[i]) and len(lineas[i]) < 60:
                flujo.append(Paragraph(inline(lineas[i].strip()), EST["meta"])); i += 1
        elif ln.startswith("|"):
            filas = []
            while i < len(lineas) and lineas[i].startswith("|"):
                celdas = [c.strip() for c in re.split(r"(?<!\\)\|", lineas[i].strip().strip("|"))]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in celdas):
                    filas.append(celdas)
                i += 1
            flujo += [tabla(filas, ancho), Spacer(1, 8)]
        elif re.match(r"- \[ \] ", ln):
            while i < len(lineas) and re.match(r"- \[ \] ", lineas[i]):
                flujo.append(Paragraph(inline(lineas[i][6:]), EST["p"], bulletText="[   ]"))
                flujo[-1].style = ParagraphStyle("t", parent=EST["p"], leftIndent=26, bulletIndent=4, bulletFontName=FM, spaceAfter=3)
                i += 1
            flujo.append(Spacer(1, 4))
        elif ln.startswith("- "):
            items = []
            while i < len(lineas) and lineas[i].startswith("- "):
                items.append(ListItem(Paragraph(inline(lineas[i][2:]), EST["p"]), leftIndent=14)); i += 1
            flujo.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=14, bulletFontName=F))
        elif re.match(r"\d+\. ", ln):
            items, primero = [], int(re.match(r"(\d+)\.", ln).group(1))
            while i < len(lineas) and re.match(r"\d+\. ", lineas[i]):
                items.append(ListItem(Paragraph(inline(re.sub(r"^\d+\.\s+", "", lineas[i])), EST["p"]), leftIndent=16)); i += 1
            flujo.append(ListFlowable(items, bulletType="1", start=primero, leftIndent=16, bulletFontName=FB))
        else:
            partes = []
            while i < len(lineas) and lineas[i].strip() and not lineas[i].startswith(("#", "|", "- ")) and not re.match(r"\d+\. ", lineas[i]):
                partes.append(lineas[i].strip()); i += 1
            flujo.append(Paragraph(inline(" ".join(partes)), EST["p"]))
    return flujo


def main(entrada: str, salida: str, encabezado: str = "NoAIVerdad") -> None:
    with open(entrada, encoding="utf-8") as f:
        md = f.read()
    w, h = A4
    doc = SimpleDocTemplate(salida, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.1 * cm, bottomMargin=1.8 * cm,
                            title=re.search(r"^# (.+)$", md, re.M).group(1) if re.search(r"^# (.+)$", md, re.M) else encabezado, author="NoAIVerdad")

    def pagina(c, d):
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, h - 1.1 * cm, w, 1.1 * cm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FB, 9)
        c.drawString(2 * cm, h - 0.72 * cm, encabezado)
        c.setFillColor(GRIS)
        c.setFont(F, 8.5)
        c.drawRightString(w - 2 * cm, 1.0 * cm, f"Página {d.page}")
        c.restoreState()

    doc.build(construir(md, w - 4 * cm), onFirstPage=pagina, onLaterPages=pagina)
    print(f"Listo: {salida}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "NoAIVerdad")
