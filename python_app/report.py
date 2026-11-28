"""Supplier cross check report: every line bought from a supplier, by travel date.

Supplier invoices go by travel date, so each line is placed on its own travel date.
Hotels and group additional charges have no date of their own, so they use the first day
of the trip. Money is added up in cents (whole numbers) so totals never drift by a cent.
"""
import csv
import io

from helpers import is_valid_date

UNKNOWN_SUPPLIER = "(No supplier set)"


def cents(value):
    try:
        return int(round(float(value or 0) * 100))
    except (TypeError, ValueError):
        return 0


def from_cents(c):
    return f"{c / 100:.2f}"


def _opt(value):
    try:
        return None if value in ("", None) else float(value)
    except (TypeError, ValueError):
        return None


def _supplier(x):
    return (x.get("supplier") or "").strip() or UNKNOWN_SUPPLIER


def lines_of_quote(q):
    """Every supplier line on one saved quote, as (type, line) pairs in one simple shape."""
    trip_dates = sorted(d for d in
                        [l.get("travelDate") or l.get("date") or "" for l in (q.get("tickets") or []) + (q.get("transport") or [])]
                        + [l.get("travelDate") or "" for l in (q.get("meals") or []) + (q.get("guides") or [])]
                        + [d.get("date") or "" for d in q.get("days") or []] if is_valid_date(d))
    trip_start = trip_dates[0] if trip_dates else ""
    out = []
    for t in q.get("tickets") or []:
        out.append(("Ticket", {"code": t.get("code") or "", "item": t.get("name") or "", "supplier": _supplier(t),
                               "qty": float(t.get("pax") or t.get("qty") or 0), "unit": float(t.get("unitPrice") or 0),
                               "adults": _opt(t.get("adults")), "children": _opt(t.get("children")),
                               "adultPrice": _opt(t.get("adultPrice")), "childPrice": _opt(t.get("childPrice")),
                               "total": _opt(t.get("total")), "travelDate": t.get("travelDate") or t.get("date") or ""}))
    for t in q.get("transport") or []:
        out.append(("Transport", {"code": t.get("code") or "", "item": t.get("description") or "", "supplier": _supplier(t),
                                  "qty": float(t.get("qty") or 0), "unit": float(t.get("unitPrice") or 0),
                                  "total": _opt(t.get("total")), "travelDate": t.get("travelDate") or t.get("date") or ""}))
    for t in q.get("meals") or []:
        name = " — ".join(x for x in (t.get("meal"), t.get("description")) if x) or "Meal"
        out.append(("Meal", {"code": "", "item": name, "supplier": _supplier(t),
                             "qty": float(t.get("pax") or 0), "unit": float(t.get("adultPrice") or 0),
                             "adults": _opt(t.get("adults")), "children": _opt(t.get("children")),
                             "adultPrice": _opt(t.get("adultPrice")), "childPrice": _opt(t.get("childPrice")),
                             "total": _opt(t.get("total")), "travelDate": t.get("travelDate") or ""}))
    for t in q.get("guides") or []:
        out.append(("Guide", {"code": t.get("code") or "", "item": "Guide — " + t["description"] if t.get("description") else "Guide",
                              "supplier": _supplier(t), "qty": float(t.get("qty") or 0), "unit": float(t.get("unitPrice") or 0),
                              "total": _opt(t.get("total")), "travelDate": t.get("travelDate") or ""}))
    for h in q.get("hotels") or []:
        out.append(("Hotel", {"code": "", "item": h.get("description") or "", "supplier": _supplier(h), "qty": 1.0,
                              "unit": float(h.get("amount") or 0), "total": _opt(h.get("amount")),
                              "travelDate": trip_start, "tripStart": bool(trip_start)}))
    if q.get("quoteType") == "group":
        # Additional charges only count when a supplier is filled in (otherwise they are your own charges).
        for a in q.get("additionalCharges") or []:
            if (a.get("supplier") or "").strip():
                out.append(("Additional", {"code": "", "item": a.get("description") or "", "supplier": a["supplier"].strip(),
                                           "qty": 1.0, "unit": float(a.get("amount") or 0), "total": _opt(a.get("amount")),
                                           "travelDate": trip_start, "tripStart": bool(trip_start)}))
    return out


def build_report(quotes, date_from, date_to):
    """The report for travel dates from date_from to date_to (both included)."""
    if not is_valid_date(date_from) or not is_valid_date(date_to):
        raise ValueError("From and To must be valid dates")
    if date_from > date_to:
        raise ValueError("From date is after To date")

    lines, used_quotes = [], {}
    for q in quotes:
        for kind, l in lines_of_quote(q):
            fallback = not is_valid_date(l["travelDate"])
            report_date = q.get("date", "") if fallback else l["travelDate"]
            if not is_valid_date(report_date) or not (date_from <= report_date <= date_to):
                continue
            used_quotes[q.get("id") or q.get("quoteNumber")] = q
            split = None not in (l.get("adults"), l.get("children"), l.get("adultPrice"), l.get("childPrice"))
            total = cents(l["total"]) if l["total"] is not None else cents(l["unit"]) * int(l["qty"])
            lines.append({
                "reportDate": report_date, "dateIsFallback": fallback, "tripStart": l.get("tripStart", False),
                "type": kind, "supplier": l["supplier"], "quoteNumber": str(q.get("quoteNumber", "")),
                "quoteDate": q.get("date", ""), "clientName": q.get("clientName", ""), "code": l["code"],
                "item": l["item"], "travelDate": l["travelDate"], "qty": int(l["qty"]) if l["qty"] == int(l["qty"]) else l["qty"],
                "adults": int(l["adults"]) if split else None, "children": int(l["children"]) if split else None,
                "adultCents": cents(l["adultPrice"]) if split else None, "childCents": cents(l["childPrice"]) if split else None,
                # one unit price only makes sense when every person paid the same
                "singlePrice": (not split) or l["children"] == 0 or l["adults"] == 0 or cents(l["adultPrice"]) == cents(l["childPrice"]),
                "unitCents": cents(l["childPrice"] if split and l["adults"] == 0 else l["adultPrice"]) if split else cents(l["unit"]),
                "totalCents": total,
            })
    lines.sort(key=lambda l: (l["supplier"].lower(), l["type"], l["reportDate"], l["quoteNumber"]))

    groups = {}
    for l in lines:
        g = groups.setdefault(l["supplier"], {"supplier": l["supplier"], "lines": [], "qty": 0, "totalCents": 0})
        g["lines"].append(l)
        g["qty"] += l["qty"]
        g["totalCents"] += l["totalCents"]
    groups = list(groups.values())
    return {
        "from": date_from, "to": date_to, "quoteCount": len(used_quotes), "groups": groups, "lines": lines,
        "supplierTotalCents": sum(g["totalCents"] for g in groups),
        # your service charge on quotes in the range (counted once per quote, not owed to suppliers)
        "serviceChargeCents": sum(cents(q.get("serviceCharge")) for q in used_quotes.values()),
        "missingTravelDate": sum(1 for l in lines if l["dateIsFallback"]),
        "missingSupplier": sum(1 for l in lines if l["supplier"] == UNKNOWN_SUPPLIER),
        "tripStartLines": sum(1 for l in lines if l["tripStart"]),
    }


def line_note(l):
    if l["dateIsFallback"]:
        return "No travel date on quote; quote date used"
    if l["tripStart"]:
        return ("Hotel" if l["type"] == "Hotel" else "Charge") + " has no date; first day of trip used"
    return ""


def _cell(value):
    s = "" if value is None else str(value)
    # Stop text that looks like a formula from running when opened in a spreadsheet.
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        try:
            float(s)
        except ValueError:
            s = "'" + s
    return s


def to_csv(lines):
    """CSV text that opens cleanly in Excel or Google Sheets."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Supplier", "Type", "Travel date", "Quote no", "Quote date", "Client", "Code", "Item", "Qty",
                "Adults", "Children", "Adult price", "Child price", "Unit price", "Line total", "Note"])
    for l in lines:
        w.writerow([_cell(x) for x in [
            l["supplier"], l["type"], l["travelDate"], l["quoteNumber"], l["quoteDate"], l["clientName"], l["code"],
            l["item"], l["qty"], "" if l["adults"] is None else l["adults"], "" if l["children"] is None else l["children"],
            "" if l["adultCents"] is None else from_cents(l["adultCents"]),
            "" if l["childCents"] is None else from_cents(l["childCents"]),
            from_cents(l["unitCents"]) if l["singlePrice"] else "", from_cents(l["totalCents"]), line_note(l)]])
    return "﻿" + buf.getvalue()  # the ﻿ mark makes Excel read it as UTF-8
