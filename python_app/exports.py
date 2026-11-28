"""Drawing quotes and invoices as PDF (with the fpdf2 library) and PNG.

Everything is measured in millimetres on an A4 page (210 mm wide, 297 mm tall).
The PNG is the same drawing on one long page, turned into a picture with pypdfium2.

The look copies the website version: a coloured stripe at the top, the business name on the
left, QUOTATION and the number on the right, then the client bar and a block per day.
"""
import base64
import io
import re
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue
import pypdfium2

from helpers import fmt_num, fmt_date, weekday, pax_label, as_int

FONTS = Path(__file__).parent / "static" / "fonts"
PAGE_W, PAGE_H = 210, 297
MARGIN = 16                    # left and right margin
CONTENT_W = PAGE_W - 2 * MARGIN
BOTTOM = PAGE_H - 16           # stop drawing here and start a new page

# Colours (red, green, blue)
INK = (15, 23, 42)
TEXT = (30, 41, 59)
MUTED = (100, 116, 139)
FAINT = (148, 163, 184)
TEAL = (13, 138, 138)
TEAL_DARK = (11, 118, 118)
GRAD_FROM, GRAD_TO = (15, 155, 142), (11, 111, 134)
BORDER = (213, 227, 230)
HEAD_BG = (238, 246, 247)
DAY_BG = (234, 244, 251)
HOTEL_BG, HOTEL_INK = (255, 243, 196), (107, 82, 0)
EXTRA_BG, EXTRA_INK = (233, 243, 255), (35, 75, 122)
PROFIT_BG = (250, 250, 250)
LINE = (226, 232, 240)
BOX_BG = (246, 249, 251)
INV_BLUE = (11, 111, 134)


class Paper(FPDF):
    """An A4 page with the Inter font loaded and a few drawing helpers."""

    def __init__(self, height=PAGE_H):
        super().__init__(unit="mm", format=(PAGE_W, height))
        self.page_h = height
        self.set_auto_page_break(False)  # we decide where pages break ourselves
        self.set_margins(MARGIN, 0, MARGIN)
        self.add_font("Inter", "", str(FONTS / "Inter-Regular.otf"))
        self.add_font("Inter", "B", str(FONTS / "Inter-Bold.otf"))
        self.add_font("Inter", "I", str(FONTS / "Inter-SemiBold.otf"))  # "I" is used for semi-bold
        self.stripe = 2.6

    def new_page(self):
        self.add_page()
        self.gradient(0, 0, PAGE_W, self.stripe)
        self.set_y(self.stripe + 8)

    def font(self, size, style="", color=TEXT, spacing=0):
        self.set_font("Inter", style, size)
        self.set_text_color(*color)
        self.set_char_spacing(spacing)

    def gradient(self, x, y, w, h, start=GRAD_FROM, end=GRAD_TO, steps=60):
        """A left-to-right colour fade, drawn as thin strips."""
        for i in range(steps):
            t = i / (steps - 1)
            self.set_fill_color(*[round(a + (b - a) * t) for a, b in zip(start, end)])
            self.rect(x + w * i / steps, y, w / steps + 0.2, h, style="F")

    def box(self, x, y, w, h, fill=None, border=None, width=0.25):
        if fill:
            self.set_fill_color(*fill)
        if border:
            self.set_draw_color(*border)
            self.set_line_width(width)
        style = ("F" if fill else "") + ("D" if border else "")
        if style:
            self.rect(x, y, w, h, style=style)

    def wrap(self, text, width):
        """Split text into the lines it needs to fit in `width` mm (uses the current font)."""
        if not text:
            return [""]
        return self.multi_cell(width, 5, text, dry_run=True, output=MethodReturnValue.LINES)

    def write_lines(self, x, y, w, lines, line_h, align="L"):
        for i, line in enumerate(lines):
            self.set_xy(x, y + i * line_h)
            self.cell(w, line_h, line, align=align)

    def at_bottom(self):
        return self.page_h != PAGE_H  # one long page (PNG): never break


def _png_from_pdf(pdf_bytes, scale=2):
    """Turn a one-page PDF into a PNG picture (scale 2 = sharp on any screen)."""
    doc = pypdfium2.PdfDocument(pdf_bytes)
    image = doc[0].render(scale=scale * 96 / 72).to_pil()
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _make(draw, kind):
    """Draw with draw(paper). For a PNG, draw once to measure, then on one page that fits."""
    if kind == "pdf":
        paper = Paper()
        draw(paper)
        return bytes(paper.output())
    tall = Paper(height=3000)
    draw(tall)
    paper = Paper(height=tall.get_y() + 12)
    draw(paper)
    return _png_from_pdf(bytes(paper.output()))


# ================================================================ TRAVEL QUOTE

def quote_file(q, settings, kind="pdf", itemised=True):
    """The quote as PDF or PNG bytes."""
    return _make(lambda p: _draw_quote(p, q, settings, itemised), kind)


def quote_filename(q, itemised, ext):
    client = re.sub(r"[^A-Za-z0-9]+", "_", q.get("clientName") or "client").strip("_")[:40]
    return f"{q.get('quoteNumber')}_{client}{'' if itemised else '_summary'}.{ext}"


def _draw_quote(p, q, settings, itemised):
    p.new_page()
    cur = q.get("currency") or settings.get("currency", "")
    mode = settings.get("profitDisplay") or "service"

    # ---- heading: business on the left, QUOTATION + number + date on the right
    top = p.get_y() + 6
    p.font(15.5, "B", INK)
    name_lines = p.wrap(settings.get("businessName", ""), 110)
    p.write_lines(MARGIN, top, 110, name_lines, 7)
    y_left = top + 7 * len(name_lines)
    if settings.get("businessDetails"):
        p.font(9, "", MUTED)
        det = [l for part in settings["businessDetails"].split("\n") for l in p.wrap(part, 110)]
        p.write_lines(MARGIN, y_left + 1, 110, det, 4.4)
        y_left += 1 + 4.4 * len(det)
    p.font(9, "B", TEAL_DARK, spacing=1.6)
    p.set_xy(PAGE_W - MARGIN - 70, top)
    p.cell(70, 5, "QUOTATION", align="R")
    p.font(9, "", (71, 85, 105))
    p.set_xy(PAGE_W - MARGIN - 70, top + 7)
    p.cell(70, 5, f"No. {q.get('quoteNumber', '')}", align="R")
    p.set_xy(PAGE_W - MARGIN - 70, top + 12)
    p.cell(70, 5, f"Date: {fmt_date(q.get('date'))}", align="R")
    y = max(y_left, top + 17) + 5
    p.box(MARGIN, y, CONTENT_W, 0.3, fill=LINE)
    y += 6

    # ---- the table
    date_w, total_w = 40, (37 if itemised else 0)
    mid_w = CONTENT_W - date_w - total_w
    group_a, group_c = as_int(q.get("adults")), as_int(q.get("children"))

    def row_height(text, width):
        p.font(10)
        return max(9.5, 5 * len(p.wrap(text, width - 6)) + 4.5)

    def new_page_if_needed(h):
        nonlocal y
        if not p.at_bottom() and y + h > BOTTOM:
            p.new_page()
            y = p.get_y()
            return True
        return False

    # client bar
    bar = f"{(q.get('clientName') or '').upper()} ({pax_label(group_a, group_c)})" + (" · GROUP" if q.get("quoteType") == "group" else "")
    p.gradient(MARGIN, y, CONTENT_W, 13)
    p.font(11.5, "I", (255, 255, 255), spacing=0.4)
    p.set_xy(MARGIN, y)
    p.cell(CONTENT_W, 13, bar, align="C")
    y += 13

    def column_heads():
        nonlocal y
        p.font(8, "I", (51, 65, 85), spacing=0.8)
        heads = [(date_w, "DATE", "C"), (mid_w, "TRANSPORT AND ATTRACTIONS", "C")] + ([(total_w, "TOTAL", "R")] if itemised else [])
        x = MARGIN
        for w, text, align in heads:
            p.box(x, y, w, 8.5, fill=HEAD_BG, border=BORDER)
            p.set_xy(x + 3, y)
            p.cell(w - 6, 8.5, text, align=align)
            x += w
        y += 8.5
    column_heads()

    def draw_block(tag_lines, tag_style, rows):
        """One block: a left cell (date or HOTEL) next to its rows of (label, amount)."""
        nonlocal y
        heights = [row_height(label, mid_w) for label, _ in rows]
        # A block that fits on one page is moved to the next page whole rather than cut.
        if not p.at_bottom() and y + sum(heights) > BOTTOM and sum(heights) <= BOTTOM - 40:
            new_page_if_needed(sum(heights))
        start = y
        for (label, amount), h in zip(rows, heights):
            if not p.at_bottom() and y + h > BOTTOM and y > start:
                _left_cell(p, start, y, date_w, tag_lines, tag_style)  # finish this page's part
                new_page_if_needed(h)
                start = y
            x = MARGIN + date_w
            p.box(x, y, mid_w, h, border=BORDER, fill=(255, 255, 255))
            p.font(10, "I" if tag_style == "profit" else "", TEXT)
            lines = p.wrap(label, mid_w - 6)
            p.write_lines(x + 3, y + (h - 5 * len(lines)) / 2, mid_w - 6, lines, 5, align="R" if tag_style == "profit" else "C")
            if itemised:
                p.box(x + mid_w, y, total_w, h, border=BORDER, fill=PROFIT_BG if tag_style == "profit" else (255, 255, 255))
                p.font(10, "", TEXT)
                p.set_xy(x + mid_w + 3, y)
                p.cell(total_w - 6, h, amount, align="R")
            y += h
        _left_cell(p, start, y, date_w, tag_lines, tag_style)

    days = q.get("days") or []
    for di, day in enumerate(days):
        if not day.get("lines"):
            continue
        rows = []
        for l in day["lines"]:
            kind = l.get("type")
            if kind == "ticket":
                label = l.get("name") or ""
                if as_int(l.get("adults")) != group_a or as_int(l.get("children")) != group_c:
                    label += f" ({pax_label(l.get('adults'), l.get('children'))})"
            elif kind == "meal":
                label = (l.get("meal") or "") + (f" — {l['description']}" if l.get("description") else "")
                if as_int(l.get("adults")) != group_a or as_int(l.get("children")) != group_c:
                    label += f" ({pax_label(l.get('adults'), l.get('children'))})"
            elif kind == "guide":
                label = "Guide" + (f" — {l['description']}" if l.get("description") else "")
            else:
                label = l.get("description") or ""
            if kind in ("transport", "guide") and as_int(l.get("qty")) > 1:
                label += f" × {as_int(l.get('qty'))}"
            rows.append((label, fmt_num(l.get("total", 0))))
        if di > 0:
            y += 3.5
        draw_block([fmt_date(day.get("date")), weekday(day.get("date"))], "day", rows)

    if q.get("hotels"):
        y += 3.5
        draw_block(["HOTEL"], "hotel", [(h.get("description", ""), fmt_num(h.get("amount", 0))) for h in q["hotels"]])
    extras = (q.get("additionalCharges") or []) if q.get("quoteType") == "group" else []
    if extras:
        y += 3.5
        draw_block(["ADDITIONAL"], "extra", [(x.get("description", ""), fmt_num(x.get("amount", 0))) for x in extras])
    if itemised and mode != "hide" and float(q.get("serviceCharge") or 0) > 0:
        draw_block([""], "profit", [("PROFIT" if mode == "profit" else "Service charge", fmt_num(q["serviceCharge"]))])

    # TOTAL bar
    new_page_if_needed(12)
    total_text = (cur + " " if cur else "") + fmt_num(q.get("total", 0))
    p.box(MARGIN + date_w, y, mid_w + total_w, 12, fill=TEAL)
    p.font(11.5, "B", (255, 255, 255))
    if itemised:
        p.set_xy(MARGIN + date_w + 3, y)
        p.cell(mid_w - 6, 12, "TOTAL", align="R")
        p.set_xy(MARGIN + date_w + mid_w + 2, y)
        p.cell(total_w - 5, 12, total_text, align="R")
    else:
        p.set_xy(MARGIN + date_w + 3, y)
        p.cell(mid_w - 6, 12, "TOTAL   " + total_text, align="R")
    y += 12

    # notes and footer
    for title, text, size, color in (("Notes", q.get("notes"), 9, (51, 65, 85)), (None, settings.get("footer"), 8.3, FAINT)):
        if not text:
            continue
        p.font(size, "", color)
        lines = [l for part in text.split("\n") for l in p.wrap(part, CONTENT_W)]
        need = 4.6 * len(lines) + (14 if title is None else 12)
        new_page_if_needed(need)
        if title:
            y += 7
            p.font(9, "B", INK)
            p.set_xy(MARGIN, y)
            p.cell(CONTENT_W, 5, title)
            y += 5
            p.font(size, "", color)
        else:
            y += 10
            p.box(MARGIN, y, CONTENT_W, 0.3, fill=LINE)
            y += 3
        p.write_lines(MARGIN, y, CONTENT_W, lines, 4.6)
        y += 4.6 * len(lines)
    p.set_y(y)


def _left_cell(p, top, bottom, w, lines, style):
    """The date cell (or HOTEL / ADDITIONAL tag) beside a block of rows."""
    fill, color, size, weight = {"day": (DAY_BG, INK, 10, "B"), "hotel": (HOTEL_BG, HOTEL_INK, 9, "B"),
                                 "extra": (EXTRA_BG, EXTRA_INK, 9, "B"), "profit": (PROFIT_BG, INK, 9, "")}[style]
    p.box(MARGIN, top, w, bottom - top, fill=fill, border=BORDER)
    mid = top + (bottom - top) / 2
    if style == "day":
        p.font(10, "B", INK)
        p.set_xy(MARGIN, mid - 5)
        p.cell(w, 5, lines[0], align="C")
        p.font(8.5, "", MUTED)
        p.set_xy(MARGIN, mid)
        p.cell(w, 5, lines[1], align="C")
    elif lines[0]:
        p.font(size, weight, color, spacing=0.8)
        p.set_xy(MARGIN, mid - 2.5)
        p.cell(w, 5, lines[0], align="C")


# ================================================================ INVOICE

def invoice_file(v, logo, kind="pdf", itemised=True):
    return _make(lambda p: _draw_invoice(p, v, logo, itemised), kind)


def invoice_filename(v, itemised, ext):
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{v.get('invoiceNumber')}_{(v.get('billTo') or {}).get('name') or 'client'}")
    return re.sub(r"_+", "_", name).strip("_")[:60] + ("" if itemised else "_summary") + "." + ext


def logo_bytes(data_url):
    """'data:image/png;base64,....' -> the picture's bytes, or None."""
    m = re.fullmatch(r"data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/=]+)", data_url or "")
    return base64.b64decode(m.group(2)) if m else None


def _draw_invoice(p, v, logo, itemised):
    p.stripe = 1.6
    p.new_page()
    cur = v.get("currency") or ""
    money = lambda n: (cur + " " if cur else "") + fmt_num(n)
    company, bill = v.get("company") or {}, v.get("billTo") or {}
    y = p.get_y() + 4

    def new_page_if_needed(h):
        nonlocal y
        if not p.at_bottom() and y + h > BOTTOM:
            p.new_page()
            y = p.get_y()

    def text_block(x, y0, w, text, size=9, color=MUTED, line_h=4.4):
        p.font(size, "", color)
        lines = [l for part in (text or "").split("\n") for l in p.wrap(part, w)]
        p.write_lines(x, y0, w, lines, line_h)
        return y0 + line_h * len(lines)

    # ---- heading: logo + company on the left, title + number on the right
    left_w = 110
    y_left = y
    picture = logo_bytes(logo)
    if picture:
        from PIL import Image
        img = Image.open(io.BytesIO(picture))
        w_mm = min(58, 21 * img.width / max(1, img.height))
        h_mm = w_mm * img.height / max(1, img.width)
        p.image(io.BytesIO(picture), x=MARGIN, y=y, w=w_mm, h=h_mm)
        y_left += h_mm + 3
    p.font(14.5, "B", INK)
    lines = p.wrap(company.get("name", ""), left_w)
    p.write_lines(MARGIN, y_left, left_w, lines, 6.5)
    y_left += 6.5 * len(lines)
    if company.get("details"):
        y_left = text_block(MARGIN, y_left + 0.8, left_w, company["details"], 8.7)

    right_x, right_w = PAGE_W - MARGIN - 64, 64
    p.font(15, "B", INV_BLUE, spacing=1)
    title_lines = p.wrap(v.get("title", "").upper(), right_w)
    for i, line in enumerate(title_lines):
        p.set_xy(right_x, y + i * 6.5)
        p.cell(right_w, 6.5, line, align="R")
    ym = y + 6.5 * len(title_lines) + 2
    meta = [("No.", v.get("invoiceNumber", "")), ("Date", fmt_date(v.get("date")))]
    if v.get("validUntil"):
        meta.append(("Valid until", fmt_date(v["validUntil"])))
    for label, value in meta:
        p.font(9, "I", INK)
        value_w = p.get_string_width(value)
        p.set_xy(right_x, ym)
        p.cell(right_w, 5, value, align="R")
        p.font(9, "", MUTED)
        p.set_xy(right_x, ym)
        p.cell(right_w - value_w - 4, 5, label, align="R")
        ym += 5
    y = max(y_left, ym) + 5
    p.box(MARGIN, y, CONTENT_W, 0.5, fill=INK)
    y += 6

    # ---- Bill to / Reference boxes
    boxes = [("BILL TO", bill.get("name", ""), bill.get("details", ""))]
    if v.get("reference"):
        boxes.append(("REFERENCE", "", v["reference"]))
    gap = 5
    bw = (CONTENT_W - gap * (len(boxes) - 1)) / len(boxes)
    heights = []
    for label, name, details in boxes:
        p.font(11.5, "B")
        h = 4 + 5 + (6 * len(p.wrap(name, bw - 8)) if name else 0)
        p.font(9.3)
        h += 4.5 * len([l for part in details.split("\n") for l in p.wrap(part, bw - 8)]) if details else 0
        heights.append(h + 4)
    bh = max(heights)
    for i, (label, name, details) in enumerate(boxes):
        x = MARGIN + i * (bw + gap)
        p.box(x, y, bw, bh, fill=BOX_BG)
        p.font(7.8, "B", INV_BLUE, spacing=1.2)
        p.set_xy(x + 4, y + 3)
        p.cell(bw - 8, 4, label)
        yy = y + 8
        if name:
            p.font(11.5, "B", INK)
            lines = p.wrap(name, bw - 8)
            p.write_lines(x + 4, yy, bw - 8, lines, 6)
            yy += 6 * len(lines)
        if details:
            text_block(x + 4, yy, bw - 8, details, 9.3, TEXT, 4.5)
    y += bh + 6

    # ---- the lines
    n_w, num_w = 7, 27
    desc_w = CONTENT_W - n_w - (3 * num_w if itemised else 0)

    def items_head():
        nonlocal y
        p.box(MARGIN, y, CONTENT_W, 8, fill=INK)
        p.font(7.3, "B", (255, 255, 255), spacing=0.5)
        cols = [(n_w, "#", "C"), (desc_w, "DESCRIPTION", "L")]
        if itemised:
            cols += [(num_w, "QTY", "R"), (num_w, "UNIT PRICE", "R"), (num_w, "AMOUNT" + (f" ({cur})" if cur else ""), "R")]
        x = MARGIN
        for w, text, align in cols:
            p.set_xy(x + 1.5, y)
            p.cell(w - 3, 8, text, align=align)
            x += w
        y += 8
    items_head()
    for i, item in enumerate(v.get("items") or []):
        p.font(9.5)
        lines = [l for part in (item.get("description") or "").split("\n") for l in p.wrap(part, desc_w - 4)]
        h = 4.8 * len(lines) + 4.5
        if not p.at_bottom() and y + h > BOTTOM:
            p.new_page()
            y = p.get_y()
            items_head()
        p.font(9.5, "", MUTED)
        p.set_xy(MARGIN, y + 2.2)
        p.cell(n_w, 4.8, str(i + 1), align="C")
        p.font(9.5, "", INK)
        p.write_lines(MARGIN + n_w + 2, y + 2.2, desc_w - 4, lines, 4.8)
        if itemised:
            x = MARGIN + n_w + desc_w
            for text in (fmt_qty(item.get("qty")), fmt_num(item.get("unitPrice", 0)), fmt_num(item.get("amount", 0))):
                p.set_xy(x, y + 2.2)
                p.cell(num_w - 2, 4.8, text, align="R")
                x += num_w
        y += h
        p.box(MARGIN, y - 0.25, CONTENT_W, 0.25, fill=LINE)

    # ---- totals, on the right
    rows = []
    if float(v.get("discount") or 0) > 0 or float(v.get("tax") or 0) > 0:
        rows.append(("Subtotal", money(v.get("subtotal", 0))))
    if float(v.get("discount") or 0) > 0:
        rows.append(("Discount", "− " + money(v["discount"])))
    if float(v.get("tax") or 0) > 0:
        rows.append((f"{v.get('taxLabel') or 'Tax'} {fmt_qty(v.get('taxRate'))}%", money(v["tax"])))
    new_page_if_needed(len(rows) * 6 + 18)
    y += 4
    tw, tx = 80, PAGE_W - MARGIN - 80
    for label, value in rows:
        p.font(9.8, "", (71, 85, 105))
        p.set_xy(tx + 3, y)
        p.cell(tw / 2, 6, label)
        p.set_xy(tx + tw / 2, y)
        p.cell(tw / 2 - 3, 6, value, align="R")
        y += 6
    p.box(tx, y + 1, tw, 10, fill=INV_BLUE)
    p.font(11.3, "B", (255, 255, 255))
    p.set_xy(tx + 3, y + 1)
    p.cell(tw / 2, 10, "Total")
    p.set_xy(tx + tw / 3, y + 1)
    p.cell(tw * 2 / 3 - 3, 10, money(v.get("total", 0)), align="R")
    y += 15

    # ---- notes, payment, terms, signature
    for label, text in (("NOTES", v.get("notes")), ("PAYMENT DETAILS", v.get("payment")), ("TERMS", v.get("terms"))):
        if not text:
            continue
        p.font(9)
        n = len([l for part in text.split("\n") for l in p.wrap(part, CONTENT_W)])
        new_page_if_needed(4.4 * n + 11)
        y += 4
        p.font(7.8, "B", INV_BLUE, spacing=1.2)
        p.set_xy(MARGIN, y)
        p.cell(CONTENT_W, 4, label)
        y = text_block(MARGIN, y + 5, CONTENT_W, text, 9, (51, 65, 85))
    new_page_if_needed(32)
    y += 6
    p.box(MARGIN, y + 10, 63, 0.3, fill=FAINT)
    p.font(9, "", (51, 65, 85))
    p.set_xy(MARGIN, y + 12)
    p.cell(63, 5, "Authorised signature")
    p.font(8.5, "", MUTED)
    p.set_xy(MARGIN, y + 17)
    p.cell(63, 5, f"for {company.get('name', '')}")
    y += 24
    if re.search("proforma", v.get("title") or "", re.I):
        new_page_if_needed(12)
        y += 6
        p.box(MARGIN, y, CONTENT_W, 0.3, fill=LINE)
        p.font(8, "", FAINT)
        p.set_xy(MARGIN, y + 2.5)
        p.cell(CONTENT_W, 5, "This is a proforma invoice, not a tax invoice. A final invoice will be issued on payment.")
        y += 8
    p.set_y(y)


def fmt_qty(n):
    """2.0 -> '2', 1.5 -> '1.5'"""
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n or "")
    return str(int(f)) if f == int(f) else f"{f:g}"
