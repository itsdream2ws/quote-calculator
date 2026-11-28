"""Proforma invoices / general quotes: lines you write yourself, discount, tax, total.

Kept apart from travel quotes (they never show on the supplier report).

The invoice being edited (the draft) is a dict:
  { id, createdBy, autoNumber, invoiceNumber, title, date, validUntil, reference,
    companyName, companyDetails, clientName, clientDetails, currency,
    items: [ {description, qty, unitPrice}, ... ],
    discount, taxLabel, taxRate, notes, payment, terms, itemised }
build_invoice() turns it into the saved record (same shape as the website, see ../DATA_FORMAT.md).

Each agent has a *letterhead* (their logo, company name and details, payment details, terms and
tax) saved to their login, so their next invoice starts with it.
"""
import re

from helpers import round2, today, is_valid_date, to_number, num_or_zero, add_days, as_int

TITLES = ["PROFORMA INVOICE", "QUOTATION", "ESTIMATE", "INVOICE"]


def letterhead(profiles, agent, settings):
    """The agent's saved letterhead, with sensible defaults for anything not saved yet."""
    business = settings.get("businessName", "")
    out = {"logo": "", "companyName": "" if business == "Your Business Name" else business,
           "companyDetails": settings.get("businessDetails", ""), "payment": "",
           "terms": "Prices are valid until the date shown. Payment confirms the booking.",
           "taxLabel": "GST", "taxRate": 0, "validDays": 14}
    out.update((profiles or {}).get(agent) or {})
    return out


def next_invoice_number(invoices, date, agent):
    """PI-20261128-AG01-001 (the agent code keeps numbers unique when working offline)."""
    prefix = f"PI-{(date or today()).replace('-', '')}-{agent}-"
    used = [int(m.group(1)) for v in invoices
            for m in [re.fullmatch(re.escape(prefix) + r"(\d+)", v.get("invoiceNumber") or "")] if m]
    return prefix + f"{max(used, default=0) + 1:03d}"


def blank_item():
    return {"description": "", "qty": 1, "unitPrice": ""}


def blank_draft(invoices, profiles, agent, settings):
    p = letterhead(profiles, agent, settings)
    d = today()
    return {"id": None, "createdBy": "", "autoNumber": True, "invoiceNumber": next_invoice_number(invoices, d, agent),
            "title": TITLES[0], "date": d, "validUntil": add_days(d, int(p["validDays"])) if p.get("validDays") else "",
            "reference": "", "companyName": p["companyName"], "companyDetails": p["companyDetails"],
            "clientName": "", "clientDetails": "", "currency": settings.get("currency") or "SGD",
            "items": [blank_item()], "discount": 0, "taxLabel": p["taxLabel"], "taxRate": p["taxRate"],
            "notes": "", "payment": p["payment"], "terms": p["terms"], "itemised": True}


def draft_from_invoice(v):
    company, bill = v.get("company") or {}, v.get("billTo") or {}
    return {"id": v.get("id"), "createdBy": v.get("createdBy") or "", "autoNumber": False,
            "invoiceNumber": v.get("invoiceNumber"), "title": v.get("title") or TITLES[0], "date": v.get("date"),
            "validUntil": v.get("validUntil") or "", "reference": v.get("reference") or "",
            "companyName": company.get("name", ""), "companyDetails": company.get("details", ""),
            "clientName": bill.get("name", ""), "clientDetails": bill.get("details", ""), "currency": v.get("currency") or "",
            "items": [{"description": l.get("description", ""), "qty": l.get("qty"), "unitPrice": l.get("unitPrice")}
                      for l in v.get("items") or []],
            "discount": v.get("discount") or 0, "taxLabel": v.get("taxLabel") or "", "taxRate": v.get("taxRate") or 0,
            "notes": v.get("notes") or "", "payment": v.get("payment") or "", "terms": v.get("terms") or "",
            "itemised": v.get("itemised") is not False}


def clean_draft(d):
    """Fill in anything missing from a draft that came from the browser."""
    out = {"id": None, "createdBy": "", "autoNumber": True, "invoiceNumber": "", "title": TITLES[0], "date": today(),
           "validUntil": "", "reference": "", "companyName": "", "companyDetails": "", "clientName": "",
           "clientDetails": "", "currency": "SGD", "items": [], "discount": 0, "taxLabel": "", "taxRate": 0,
           "notes": "", "payment": "", "terms": "", "itemised": True}
    out.update({k: v for k, v in (d or {}).items() if k in out})
    out["items"] = [i for i in out["items"] if isinstance(i, dict)] if isinstance(out["items"], list) else []
    return out


# ---------------------------------------------------------------- totals

def line_amount(item):
    q, p = to_number(item.get("qty")), to_number(item.get("unitPrice"))
    return 0.0 if q is None or p is None else round2(q * p)


def calc(d):
    subtotal = round2(sum(line_amount(i) for i in d["items"]))
    discount = round2(max(0.0, num_or_zero(d.get("discount"))))
    rate = max(0.0, num_or_zero(d.get("taxRate")))
    tax = round2((subtotal - discount) * rate / 100)
    return {"subtotal": subtotal, "discount": discount, "rate": rate, "tax": tax,
            "total": round2(subtotal - discount + tax)}


# ---------------------------------------------------------------- checks before saving

def validate(d, invoices):
    """Returns (errors, bad_fields). bad_fields are paths like 'items.0.qty'."""
    errors, bad = [], []

    def err(text, path=None):
        if text not in errors:
            errors.append(text)
        if path:
            bad.append(path)

    if not str(d["companyName"]).strip():
        err("Enter your company name.", "companyName")
    number = str(d["invoiceNumber"] or "").strip()
    if not number:
        err("Enter a document number.", "invoiceNumber")
    elif any(v["invoiceNumber"].lower() == number.lower() and v["id"] != d["id"] for v in invoices):
        err(f"Number {number} is already used by another saved invoice.", "invoiceNumber")
    if not is_valid_date(d["date"] or ""):
        err("Enter the date.", "date")
    if d["validUntil"] and (not is_valid_date(d["validUntil"]) or (is_valid_date(d["date"] or "") and d["validUntil"] < d["date"])):
        err('"Valid until" must be on or after the date.', "validUntil")
    if not str(d["clientName"]).strip():
        err("Enter who the invoice is for (Bill to).", "clientName")
    if not d["items"]:
        err("Add at least one line.")
    for i, item in enumerate(d["items"]):
        n = f"Line {i + 1}: "
        if not str(item.get("description") or "").strip():
            err(n + "write a description.", f"items.{i}.description")
        q = to_number(item.get("qty"))
        if q is None or q <= 0:
            err(n + "quantity must be more than 0.", f"items.{i}.qty")
        p = to_number(item.get("unitPrice"))
        if p is None or p < 0:
            err(n + "enter a unit price (0 or more).", f"items.{i}.unitPrice")
    t = calc(d)
    disc = to_number(d.get("discount"))
    if d.get("discount") not in ("", None) and (disc is None or disc < 0):
        err("Discount must be 0 or more.", "discount")
    elif t["discount"] > t["subtotal"]:
        err("Discount is more than the subtotal.", "discount")
    rate = to_number(d.get("taxRate"))
    if d.get("taxRate") not in ("", None) and (rate is None or rate < 0 or rate > 100):
        err("Tax rate must be between 0 and 100.", "taxRate")
    if not str(d["currency"] or "").strip():
        err("Enter the currency.", "currency")
    return errors, bad


# ---------------------------------------------------------------- buttons

def apply_action(d, action, invoices, agent):
    name, i = action.get("name"), int(action.get("index", 0) or 0)
    items = d["items"]
    if name == "add_item":
        items.append(blank_item())
        return f"items.{len(items) - 1}.description"
    if name == "del_item" and 0 <= i < len(items):
        items.pop(i)
    elif name == "up" and 0 < i < len(items):
        items[i - 1], items[i] = items[i], items[i - 1]
    elif name == "down" and 0 <= i < len(items) - 1:
        items[i + 1], items[i] = items[i], items[i + 1]
    elif name == "date_changed" and d.get("autoNumber") and not d.get("id") and is_valid_date(d["date"] or ""):
        d["invoiceNumber"] = next_invoice_number(invoices, d["date"], agent)
    return None


# ---------------------------------------------------------------- saving

def build_invoice(d):
    t = calc(d)
    return {
        "title": str(d["title"] or "").strip() or TITLES[0], "date": d["date"], "validUntil": d["validUntil"] or "",
        "reference": str(d["reference"] or "").strip(),
        "company": {"name": str(d["companyName"]).strip(), "details": str(d["companyDetails"] or "").strip()},
        "billTo": {"name": str(d["clientName"]).strip(), "details": str(d["clientDetails"] or "").strip()},
        "currency": str(d["currency"] or "").strip(),
        "items": [{"description": str(i.get("description") or "").strip(), "qty": as_int(i.get("qty")),
                   "unitPrice": round2(i.get("unitPrice")), "amount": line_amount(i)} for i in d["items"]],
        "subtotal": t["subtotal"], "discount": t["discount"], "taxLabel": str(d["taxLabel"] or "").strip(),
        "taxRate": as_int(t["rate"]), "tax": t["tax"], "total": t["total"],
        "notes": str(d["notes"] or "").strip(), "payment": str(d["payment"] or "").strip(),
        "terms": str(d["terms"] or "").strip(), "itemised": d.get("itemised") is not False,
    }
