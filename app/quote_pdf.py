"""Draws the quotation as a one-page A4 PDF.

Written with reportlab so it works anywhere the app runs, including a hosted
server with nothing else installed - the old route shelled out to LibreOffice,
which is not present on a web host.  The layout follows the same proportions as
the .xlsx: the six column widths, the black title bar, the red terms block, the
blue bank header and the footer text all match.

The bundled GNU FreeFont carries the rupee sign, which the PDF core fonts do
not.
"""

import os

from reportlab.lib.colors import Color, black, blue, red, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
SERIF = "WWSerif"
SERIF_BOLD = "WWSerif-Bold"

MARGIN = 10 * mm
PAGE_W, PAGE_H = A4
CONTENT_W = PAGE_W - 2 * MARGIN

# The .xlsx column widths, as fractions of the printable width.
_COLS = [5.38, 46.25, 9.13, 5.75, 10.38, 16.75]
COL_W = [CONTENT_W * c / sum(_COLS) for c in _COLS]

MIN_ITEM_ROWS = 7
ROW_H = 5.2 * mm

NOTES = [
    "Goods Once sold will not be taken back",
    "Our responsibility ceases once the goods leave our godown",
    "Payment by crossed cheque is requested",
    "Subject to Mumbai jurisdiction (s) E. &amp; O.E",
]

DECLARATION = (
    "I / We hereby certify that my / our registration certificate under the GST is "
    "in force on the date on which the sale of the goods specified in this tax "
    "invoice is made by me / us and that the transaction of the sale covered by this "
    "tax invoice has been effected by me / us and it shall be accounted for in the "
    "turnover of sales while filing of return and the due tax, if any, payable on "
    "the sale has been paid or shall be paid"
)

_fonts_ready = False


def _register_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont(SERIF, os.path.join(FONT_DIR, "FreeSerif.ttf")))
    pdfmetrics.registerFont(TTFont(SERIF_BOLD, os.path.join(FONT_DIR, "FreeSerifBold.ttf")))
    pdfmetrics.registerFontFamily(SERIF, normal=SERIF, bold=SERIF_BOLD)
    _fonts_ready = True


def rupees(value):
    """1234567.5 -> ₹12,34,567.50, grouped the Indian way."""
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    whole, paise = divmod(round(abs(amount) * 100), 100)
    digits = str(int(whole))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join(parts) + "," + tail
    sign = "-" if amount < 0 else ""
    return f"{sign}₹{digits}.{paise:02d}"


def plain(value, decimals=2):
    try:
        return f"{float(value or 0):,.{decimals}f}"
    except (TypeError, ValueError):
        return ""


def _esc(text):
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\n", "<br/>"))


def _style(size, bold=False, align=TA_LEFT, leading=None, color=black):
    return ParagraphStyle(
        f"s{size}{bold}{align}",
        fontName=SERIF_BOLD if bold else SERIF,
        fontSize=size, leading=leading or size * 1.22,
        alignment=align, textColor=color,
    )


def _draw_para(c, text, style, x, y_top, width, max_height=None):
    """Draw wrapped text with its top edge at y_top; returns the height used."""
    para = Paragraph(_esc(text), style)
    _, height = para.wrapOn(c, width, max_height or PAGE_H)
    para.drawOn(c, x, y_top - height)
    return height


def generate_quote_pdf(quote, out_path):
    """Write the one-page quotation PDF for `quote` to `out_path`."""
    _register_fonts()
    company = quote.get("company") or {}
    items = [i for i in (quote.get("items") or [])
             if i.get("description") or i.get("model")]

    c = pdfcanvas.Canvas(out_path, pagesize=A4)
    c.setTitle(f"{quote.get('heading', 'QUOTATION')} - {quote.get('party_name', '')}")
    x0 = MARGIN
    y = PAGE_H - MARGIN

    # ---- title bar --------------------------------------------------------
    bar_h = 6 * mm
    c.setFillColor(black)
    c.rect(x0, y - bar_h, CONTENT_W, bar_h, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont(SERIF_BOLD, 12)
    c.drawCentredString(x0 + CONTENT_W / 2, y - bar_h + 1.8 * mm,
                        quote.get("heading") or "QUOTATION")
    y -= bar_h + 1.5 * mm

    # ---- date / prepared by ----------------------------------------------
    c.setFillColor(black)
    c.setFont(SERIF, 9)
    c.drawString(x0, y - 3.2 * mm, "DATE:-")
    c.setFont(SERIF_BOLD, 9)
    c.drawString(x0 + 12 * mm, y - 3.2 * mm, str(quote.get("quote_date") or "")[:16])
    prepared = " ".join(x for x in [quote.get("salesperson"),
                                    quote.get("salesperson_phone")] if x)
    c.setFont(SERIF, 9)
    c.drawRightString(x0 + CONTENT_W - 40 * mm, y - 3.2 * mm, "Prepared by")
    c.setFont(SERIF_BOLD, 9)
    c.drawRightString(x0 + CONTENT_W, y - 3.2 * mm, prepared)
    y -= 6 * mm

    # ---- our company ------------------------------------------------------
    c.setFont(SERIF_BOLD, 22)
    c.drawCentredString(x0 + CONTENT_W / 2, y - 7 * mm, company.get("name", ""))
    y -= 9.5 * mm

    address = "\n".join(x for x in [company.get("address", ""),
                                    company.get("address2", "")] if x)
    y -= _draw_para(c, address, _style(7, align=TA_CENTER, leading=9),
                    x0, y, CONTENT_W) + 2 * mm

    # ---- party ------------------------------------------------------------
    c.setFont(SERIF_BOLD, 9)
    c.drawString(x0, y - 4.4 * mm, "M/S:")
    c.setFont(SERIF, 13)
    c.drawCentredString(x0 + CONTENT_W / 2, y - 4.6 * mm, quote.get("party_name", ""))
    y -= 7 * mm

    c.setFont(SERIF_BOLD, 9)
    c.drawString(x0, y - 3.2 * mm, "ADD:")
    y -= _draw_para(c, quote.get("party_address", ""),
                    _style(8, align=TA_CENTER, leading=10),
                    x0 + 14 * mm, y, CONTENT_W - 14 * mm) + 2 * mm

    # ---- status block -----------------------------------------------------
    label_w = CONTENT_W * 0.46
    for label, value in [
        ("ORDER STATUS:-", quote.get("order_status", "")),
        ("ADVANCE:-", rupees(quote.get("advance"))),
        ("BALANCE PAYABLE:-", rupees(quote.get("balance"))),
        ("DISPATCH:-", quote.get("dispatch", "")),
    ]:
        c.setFont(SERIF_BOLD, 9)
        c.drawRightString(x0 + label_w, y - 3.4 * mm, label)
        c.drawString(x0 + label_w + 2.5 * mm, y - 3.4 * mm, str(value))
        y -= 4.6 * mm
    y -= 1.5 * mm

    # ---- item table -------------------------------------------------------
    edges = [x0]
    for w in COL_W:
        edges.append(edges[-1] + w)

    header_h = 5.5 * mm
    c.setLineWidth(0.5)
    c.setFont(SERIF_BOLD, 9)
    c.rect(x0, y - header_h, CONTENT_W, header_h, stroke=1, fill=0)
    for i, title in enumerate(["No.", "Description", "GST", "Qty", "Rate", "Amount"]):
        if i:
            c.line(edges[i], y, edges[i], y - header_h)
        c.drawCentredString((edges[i] + edges[i + 1]) / 2, y - header_h + 1.6 * mm, title)
    y -= header_h

    # Every item takes two lines: the description, then its model code.
    rows = max(len(items), MIN_ITEM_ROWS)
    table_h = rows * ROW_H * 2
    table_top = y
    c.rect(x0, y - table_h, CONTENT_W, table_h, stroke=1, fill=0)
    for i in range(1, 6):
        c.line(edges[i], table_top, edges[i], table_top - table_h)

    desc_style = _style(8.5, leading=10)
    model_style = _style(8.5, bold=True, leading=10)
    for index, item in enumerate(items):
        top = table_top - index * ROW_H * 2
        qty = float(item.get("qty") or 0)
        rate = float(item.get("rate") or 0)
        amount = float(item.get("amount") if item.get("amount") is not None
                       else qty * rate)

        c.setFont(SERIF, 8.5)
        c.drawCentredString((edges[0] + edges[1]) / 2, top - 3.7 * mm, str(index + 1))
        _draw_para(c, item.get("description", ""), desc_style,
                   edges[1] + 1.2 * mm, top - 0.8 * mm, COL_W[1] - 2.4 * mm)
        _draw_para(c, item.get("model", ""), model_style,
                   edges[1] + 1.2 * mm, top - ROW_H - 0.3 * mm, COL_W[1] - 2.4 * mm)
        c.setFont(SERIF, 8.5)
        c.drawCentredString((edges[2] + edges[3]) / 2, top - 3.7 * mm,
                            f"{float(item.get('gst_percent') or 0):.2f}%")
        c.drawCentredString((edges[3] + edges[4]) / 2, top - 3.7 * mm, plain(qty, 0))
        c.drawCentredString((edges[4] + edges[5]) / 2, top - 3.7 * mm, plain(rate))
        c.drawCentredString((edges[5] + edges[6]) / 2, top - 3.7 * mm, rupees(amount))
    y = table_top - table_h

    # ---- terms | totals + bank -------------------------------------------
    left_w = COL_W[0] + COL_W[1] + COL_W[2]
    right_x = x0 + left_w
    right_w = CONTENT_W - left_w
    head_h = 5 * mm

    c.setFillColor(red)
    c.rect(x0, y - head_h, left_w, head_h, stroke=1, fill=1)
    c.setFillColor(white)
    c.setFont(SERIF_BOLD, 9)
    c.drawString(x0 + 1.5 * mm, y - head_h + 1.4 * mm, "TERMS & CONDITIONS:-")

    c.setFillColor(black)
    for label, value in [("GST AMT", rupees(quote.get("gst_amount"))),
                         ("G.TOTAL", rupees(quote.get("grand_total")))]:
        row_y = y - head_h if label == "GST AMT" else y - head_h * 2
        c.rect(right_x, row_y, right_w, head_h, stroke=1, fill=0)
        c.line(right_x + right_w * 0.45, row_y, right_x + right_w * 0.45, row_y + head_h)
        c.setFont(SERIF, 9)
        c.drawCentredString(right_x + right_w * 0.225, row_y + 1.4 * mm, label)
        c.setFont(SERIF_BOLD, 9)
        c.drawCentredString(right_x + right_w * 0.725, row_y + 1.4 * mm, value)

    terms_h = 30 * mm
    terms_top = y - head_h
    c.setFillColor(black)
    c.rect(x0, terms_top - terms_h, left_w, terms_h, stroke=1, fill=1)
    _draw_para(c, quote.get("terms", ""),
               _style(8, bold=True, leading=10, color=white),
               x0 + 1.5 * mm, terms_top - 1.2 * mm, left_w - 3 * mm)

    bank_top = y - head_h * 2
    c.setFillColor(blue)
    c.rect(right_x, bank_top - head_h, right_w, head_h, stroke=1, fill=1)
    c.setFillColor(white)
    c.setFont(SERIF_BOLD, 9)
    c.drawCentredString(right_x + right_w / 2, bank_top - head_h + 1.4 * mm,
                        "OUR BANK DETAILS")

    c.setFillColor(black)
    # The right column carries three 5mm bands (GST, total, bank header) above
    # the bank body, so the body takes what is left of the terms block's height
    # and both columns end on the same line.
    bank_h = terms_h - 2 * head_h
    c.rect(right_x, bank_top - head_h - bank_h, right_w, bank_h, stroke=1, fill=0)
    _draw_para(c, company.get("bank_details", ""), _style(7, bold=True, leading=8.6),
               right_x + 1.5 * mm, bank_top - head_h - 1.2 * mm, right_w - 3 * mm)
    y = terms_top - terms_h - 3.5 * mm

    # ---- contact strip ----------------------------------------------------
    c.setFont(SERIF_BOLD, 9)
    c.drawCentredString(x0 + CONTENT_W / 2, y - 3.4 * mm,
                        company.get("contact_line") or "")
    y -= 6.5 * mm

    # ---- notes + signature -----------------------------------------------
    notes_w = CONTENT_W * 0.62
    note_top = y
    for index, note in enumerate(NOTES):
        c.setFont(SERIF, 8.5)
        c.drawString(x0 + 2 * mm, note_top - 3.2 * mm - index * 4.4 * mm,
                     f"{index + 1}) {note.replace('&amp;', '&')}")
    c.setFont(SERIF_BOLD, 9)
    c.drawCentredString(x0 + notes_w + (CONTENT_W - notes_w) / 2, note_top - 3.2 * mm,
                        company.get("name", ""))
    y = note_top - len(NOTES) * 4.4 * mm - 2 * mm

    # ---- declaration ------------------------------------------------------
    decl_h = _draw_para(c, DECLARATION, _style(7.5, leading=9.4), x0, y, notes_w)
    c.setFont(SERIF, 9)
    c.drawString(x0 + notes_w + 2 * mm, y - decl_h + 1 * mm,
                 "Proprietor / Authorised Signatory")

    c.showPage()
    c.save()
    return out_path
