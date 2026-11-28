"""The quote as a PDF, drawn with the fpdf2 library.

Sizes are in millimetres on an A4 page (210 x 297). pdf.table() draws the table and starts a
new page by itself when it gets to the bottom.

The PDF uses the Helvetica font that is built into every PDF reader. It only has Western
European letters, so anything else (such as Chinese characters) is shown as "?".
"""
from fpdf import FPDF
from fpdf.fonts import FontFace

import rules

TEAL = (13, 138, 138)          # the main colour: red, green, blue from 0 to 255
LIGHT = (234, 244, 251)        # the background of the date column
GREY = (100, 116, 139)


def text(value):
    """Swap the letters Helvetica can't show for '?' (and a long dash for a short one)."""
    return str(value or "").replace("—", "-").replace("–", "-").encode("latin-1", "replace").decode("latin-1")


def quote_pdf(q, settings, path):
    """Draw quote q and save it at path. q is a saved quote (see rules.build_quote)."""
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_margins(16, 16, 16)
    pdf.add_page()
    width = pdf.epw                               # the width between the margins
    itemised = q.get("itemised", True)
    currency = q.get("currency") or settings.get("currency", "")

    # ---- top: the business on the left, QUOTATION and the number on the right
    pdf.set_fill_color(*TEAL)
    pdf.rect(0, 0, 210, 3, style="F")             # a coloured stripe along the top
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(15, 23, 42)
    pdf.multi_cell(110, 7, text(settings.get("businessName")))
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(110, 4.5, text(settings.get("businessDetails")))
    bottom_left = pdf.get_y()
    pdf.set_xy(126, 16)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*TEAL)
    pdf.cell(68, 6, "QUOTATION", align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GREY)
    pdf.cell(68, 5, text("No. " + q["quoteNumber"]), align="R", new_x="LEFT", new_y="NEXT")
    pdf.cell(68, 5, "Date: " + rules.nice_date(q["date"]), align="R")
    pdf.set_y(max(bottom_left, 33) + 6)

    # ---- the client bar
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(width, 11, text(f"{q['clientName'].upper()} ({rules.pax_text(q['adults'], q['children'])})"),
             align="C", fill=True, new_x="LMARGIN", new_y="NEXT")

    # ---- the table: one group of rows per day, then hotels, extra charges and profit
    groups = []                                    # [(left cell, [(description, amount), ...]), ...]
    for day in q["days"]:
        if day["lines"]:
            groups.append((rules.nice_date(day["date"]),
                           [(rules.line_label(l, q), l["total"]) for l in day["lines"]]))
    if q.get("hotels"):
        groups.append(("HOTEL", [(h["description"], h["amount"]) for h in q["hotels"]]))
    if q.get("quoteType") == "group" and q.get("additionalCharges"):
        groups.append(("ADDITIONAL", [(a["description"], a["amount"]) for a in q["additionalCharges"]]))
    mode = settings.get("profitDisplay") or "service"
    if itemised and mode != "hide" and q.get("serviceCharge"):
        groups.append(("", [("PROFIT" if mode == "profit" else "Service charge", q["serviceCharge"])]))

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(30, 41, 59)
    pdf.set_draw_color(213, 227, 230)
    pdf.set_fill_color(255, 255, 255)
    columns = (38, width - 38 - 34, 34) if itemised else (38, width - 38)
    with pdf.table(col_widths=columns, text_align=("CENTER", "LEFT", "RIGHT")[:len(columns)], line_height=5.5,
                   padding=2, headings_style=FontFace(emphasis="BOLD", fill_color=(238, 246, 247))) as table:
        table.row(["DATE", "TRANSPORT AND ATTRACTIONS", "TOTAL"][:len(columns)])
        for left, rows in groups:
            for i, (description, amount) in enumerate(rows):
                row = table.row()
                if i == 0:                         # the date (or HOTEL) cell spans all rows of its group
                    row.cell(left, rowspan=len(rows), style=FontFace(emphasis="BOLD", fill_color=LIGHT))
                row.cell(text(description))
                if itemised:
                    row.cell(rules.fmt(amount))

    # ---- the total
    pdf.set_fill_color(*TEAL)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(width, 11, text(f"TOTAL   {currency} {rules.fmt(q['total'])}  "), align="R", fill=True,
             new_x="LMARGIN", new_y="NEXT")

    # ---- notes and the footer from the settings
    pdf.set_text_color(51, 65, 85)
    if q.get("notes"):
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(width, 5, "Notes", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(width, 4.6, text(q["notes"]))
    if settings.get("footer"):
        pdf.ln(8)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(148, 163, 184)
        pdf.multi_cell(width, 4.2, text(settings["footer"]))
    pdf.output(str(path))


def file_name(q):
    """Q-20261128-AG01-001_Tan_family.pdf"""
    client = "".join(ch if ch.isalnum() else "_" for ch in q.get("clientName") or "client").strip("_")[:40]
    return f"{q['quoteNumber']}_{client}" + ("" if q.get("itemised", True) else "_summary") + ".pdf"
