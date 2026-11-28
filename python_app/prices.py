"""Price list rules: tickets, transfers (transport) and guides.

A price list is a dict:  {"tickets": [...], "transport": [...], "guides": [...]}
  ticket:    {code, name, supplier, adultPrice, childPrice, price, validUntil, confirmedAt}
  transport: {id, code, name, supplier, price}
  guide:     {id, code, name, supplier, price}
These are the same shapes the website version uses (see ../DATA_FORMAT.md).
Every code belongs to one ticket, transfer or guide only.
"""
from helpers import (round2, today, this_month, is_valid_date, days_between,
                     to_number, norm_code, new_id, month_range)


def empty_price_list():
    return {"tickets": [], "transport": [], "guides": []}


def adult_price(t):
    return round2(t.get("adultPrice") if t.get("adultPrice") is not None else t.get("price", 0))


def child_price(t):
    """Child price; older tickets without one use the adult price."""
    c = t.get("childPrice")
    return adult_price(t) if c is None or c == "" else round2(c)


# ---------------------------------------------------------------- finding items by code

def find_ticket(prices, code):
    code = norm_code(code)
    return next((t for t in prices["tickets"] if t["code"] == code), None) if code else None


def find_transport(prices, code):
    code = norm_code(code)
    return next((t for t in prices["transport"] if t.get("code") == code), None) if code else None


def find_guide(prices, code):
    code = norm_code(code)
    return next((t for t in prices["guides"] if t.get("code") == code), None) if code else None


def code_owner(prices, code):
    """Which item uses this code? Returns (kind, item) or (None, None)."""
    for kind, finder in (("ticket", find_ticket), ("transfer", find_transport), ("guide", find_guide)):
        item = finder(prices, code)
        if item:
            return kind, item
    return None, None


def code_clash(prices, code, editing_item=None):
    """Message if another item already uses this code, else None."""
    kind, item = code_owner(prices, code)
    if item is None or item is editing_item:
        return None
    return f"Code {norm_code(code)} is already used by a {kind} ({item['name']})."


# ---------------------------------------------------------------- ticket price status

def ticket_status(t):
    """How fresh a ticket price is: ('ok'|'warn'|'bad', text to show)."""
    t0 = today()
    valid = t.get("validUntil") or ""
    if not valid or valid < t0:
        return "bad", "Expired"
    if (t.get("confirmedAt") or "")[:7] != this_month():
        return "warn", "Confirm for this month"
    left = days_between(t0, valid)
    if left <= 7:
        return "warn", f"Expires in {left} day" + ("" if left == 1 else "s")
    return "ok", "OK"


# ---------------------------------------------------------------- checking the price list forms

def check_ticket_form(prices, form, editing_code=""):
    """Check the 'Add ticket' form. Returns (ticket, error message)."""
    code = norm_code(form.get("code"))
    name = (form.get("name") or "").strip()
    supplier = (form.get("supplier") or "").strip()
    adult = to_number(form.get("adultPrice"))
    child = adult if (form.get("childPrice") or "") == "" else to_number(form.get("childPrice"))
    valid_until = form.get("validUntil") or ""
    if not code or not name or not supplier:
        return None, "Code, name and supplier are required."
    if adult is None or adult < 0:
        return None, "Adult price must be 0 or more."
    if child is None or child < 0:
        return None, "Child price must be 0 or more (or leave it blank)."
    if not is_valid_date(valid_until):
        return None, 'Enter a valid "valid until" date.'
    editing = find_ticket(prices, editing_code) if editing_code else None
    clash = code_clash(prices, code, editing)
    if clash:
        return None, clash
    ticket = {"code": code, "name": name, "supplier": supplier, "adultPrice": round2(adult),
              "childPrice": round2(child), "price": round2(adult), "validUntil": valid_until,
              "confirmedAt": today()}
    return ticket, None


def check_simple_form(prices, form, kind, editing_id=""):
    """Check the transport or guide form (they have the same fields). Returns (item, error)."""
    items = prices["transport" if kind == "transport" else "guides"]
    code = norm_code(form.get("code"))
    name = (form.get("name") or "").strip()
    supplier = (form.get("supplier") or "").strip()
    price = to_number(form.get("price"))
    if not code or not name or not supplier:
        what = "place" if kind == "guide" else "name"
        return None, f"Code, {what} and supplier are required."
    if price is None or price < 0:
        return None, "Price must be 0 or more."
    editing = next((t for t in items if t["id"] == editing_id), None) if editing_id else None
    clash = code_clash(prices, code, editing)
    if clash:
        return None, clash
    item = {"id": editing["id"] if editing else new_id(), "code": code, "name": name,
            "supplier": supplier, "price": round2(price)}
    return item, None


def suppliers(prices, quotes=()):
    """Every supplier name in the price list and on saved quotes, for the suggestion list."""
    names = set()
    for group in prices.values():
        names.update(t.get("supplier", "") for t in group)
    for q in quotes:
        for day in q.get("days") or []:
            names.update(l.get("supplier", "") for l in day.get("lines", []))
        names.update(h.get("supplier", "") for h in q.get("hotels") or [])
    return sorted(n for n in names if n)


def sample_price_list(prices):
    """Made-up sample items, for trying the app. Skips codes that are already used."""
    t0 = today()
    y, m = int(t0[:4]), int(t0[5:7])
    end = month_range(y + (m == 12), m % 12 + 1)[1]  # end of next month
    tickets = [("CT01", "City tour", "City Tours Co", 14, 10), ("SF01", "Singapore Flyer", "Singapore Flyer", 45, 29),
               ("GB01", "Gardens by the Bay", "Gardens by the Bay", 30, 22), ("NS01", "Night Safari", "Mandai Wildlife", 48, 34),
               ("CC01", "Cable car", "Mount Faber Leisure", 26, 18), ("US01", "Universal Studios", "Resorts World Sentosa", 83, 62.5)]
    transport = [("APU", "Pickup from airport", "Metro Transport", 45), ("APD", "Drop off to airport", "Metro Transport", 45),
                 ("T7R", "Transfer, 7 seater (2 way)", "Metro Transport", 80), ("T7S", "Transfer, 7 seater (1 way)", "Metro Transport", 40)]
    guides = [("GUSS", "Universal Studios (full day)", "City Guides", 180), ("GSEN", "Sentosa (half day)", "City Guides", 120),
              ("GCITY", "City tour (full day)", "City Guides", 200)]
    new = empty_price_list()
    for code, name, sup, a, c in tickets:
        if not code_owner(prices, code)[1]:
            new["tickets"].append({"code": code, "name": name, "supplier": sup, "adultPrice": a, "childPrice": c,
                                   "price": a, "validUntil": end, "confirmedAt": t0})
    for code, name, sup, p in transport:
        if not code_owner(prices, code)[1]:
            new["transport"].append({"id": new_id(), "code": code, "name": name, "supplier": sup, "price": p})
    for code, name, sup, p in guides:
        if not code_owner(prices, code)[1]:
            new["guides"].append({"id": new_id(), "code": code, "name": name, "supplier": sup, "price": p})
    return new

