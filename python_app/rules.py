"""The business rules: money, dates, the price list, quote totals and checks, and the supplier report.

Nothing in this file touches the screen, the database or the internet, so every function here is
easy to try out on its own (see test_app.py).

The data is plain Python dicts and lists, in exactly the same shape the website saves
(see ../DATA_FORMAT.md), so the website and this app can share one database.

  price list = {"tickets": [ticket, ...], "transport": [item, ...], "guides": [item, ...]}
    ticket = {code, name, supplier, adultPrice, childPrice, price, validUntil, confirmedAt}
    item   = {id, code, name, supplier, price}          (transport and guides look the same)

  quote draft (the quote being edited) = {
    id, quoteNumber,               None until saved the first time
    clientName, date, adults, children, notes, serviceCharge, itemised,
    days:   [{date, lines: [line, ...]}, ...],
    hotels: [{description, supplier, amount}, ...],
    group, additional              group quotes made on the website (this app keeps them as they are)
  }
  a line is one of:
    {type: "ticket",    code, name, supplier, adults, children, adultPrice, childPrice}
    {type: "meal",      meal, description, supplier, adults, children, adultPrice, childPrice}
    {type: "transport", code, description, supplier, qty, unitPrice}
    {type: "guide",     code, description, supplier, qty, unitPrice}
"""
import copy
import csv
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Singapore"          # "today" on quotes and price checks
MEALS = ["Breakfast", "Lunch", "Dinner"]


# =============================================================== small helpers

def round2(value):
    """Round to 2 decimals with halves going up (2.345 -> 2.35), like a calculator.
    Python's own round() would give 2.34 ("banker's rounding"), so we use Decimal."""
    try:
        return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


def num(value):
    """What was typed -> a number, or None if it isn't one.  '12' -> 12.0, '' -> None."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return None if n != n or n in (float("inf"), float("-inf")) else n


def num0(value):
    """Like num(), but 0 instead of None."""
    return num(value) or 0.0


def whole(value):
    """'2' -> 2 (an int, so it is saved as 2 and not 2.0). Not a whole number -> None."""
    n = num(value)
    return int(n) if n is not None and n == int(n) else None


def is_money(value):
    n = num(value)
    return n is not None and n >= 0


def fmt(value):
    """1234.5 -> '1,234.50'"""
    return f"{round2(value):,.2f}"


def today():
    return datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()


def now_iso():
    """The time now, like '2026-11-28T05:30:00.000Z' (the format the website saves)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def is_date(text):
    """True for a real date written as YYYY-MM-DD."""
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)) and bool(date.fromisoformat(text))
    except (TypeError, ValueError):
        return False


def nice_date(text):
    """'2026-11-28' -> 'Sat 28 Nov 2026'"""
    return date.fromisoformat(text).strftime("%a %d %b %Y") if is_date(text) else (text or "")


def add_days(text, n):
    return (date.fromisoformat(text) + timedelta(days=n)).isoformat()


def month_range(day):
    """'2026-02-14' -> ('2026-02-01', '2026-02-28')"""
    d = date.fromisoformat(day)
    first = d.replace(day=1)
    next_first = (first + timedelta(days=32)).replace(day=1)
    return first.isoformat(), (next_first - timedelta(days=1)).isoformat()


def new_id():
    return uuid.uuid4().hex[:16]


def clean_code(code):
    """' ct 01 ' -> 'CT01'"""
    return re.sub(r"\s+", "", str(code or "")).upper()


def pax_text(adults, children):
    """(2, 1) -> '2 A+1C'"""
    a, c = whole(adults) or 0, whole(children) or 0
    return f"{a} A" + (f"+{c}C" if c else "")


# =============================================================== price list

def adult_price(t):
    return round2(t.get("adultPrice") if t.get("adultPrice") is not None else t.get("price", 0))


def child_price(t):
    """Older tickets have no child price: they use the adult price."""
    return adult_price(t) if t.get("childPrice") in (None, "") else round2(t["childPrice"])


def find_code(prices, code):
    """Which ticket, transfer or guide has this code?  Returns (kind, item) or (None, None)."""
    code = clean_code(code)
    for kind, key in (("ticket", "tickets"), ("transport", "transport"), ("guide", "guides")):
        for item in prices[key]:
            if code and item.get("code") == code:
                return kind, item
    return None, None


def ticket_status(t):
    """How fresh a ticket price is: ('ok' | 'warn' | 'bad', text to show)."""
    t0 = today()
    valid = t.get("validUntil") or ""
    if valid < t0:
        return "bad", "Expired"
    if (t.get("confirmedAt") or "")[:7] != t0[:7]:
        return "warn", "Confirm for this month"
    left = (date.fromisoformat(valid) - date.fromisoformat(t0)).days
    if left <= 7:
        return "warn", f"Expires in {left} day" + ("" if left == 1 else "s")
    return "ok", "OK"


def check_price_item(prices, kind, form, editing=None):
    """Check the price list form. kind is 'ticket', 'transport' or 'guide'.
    form is a dict of what was typed. editing is the item being changed (None for a new one).
    Returns (item, None) when it's fine, or (None, error message)."""
    code, name, supplier = clean_code(form.get("code")), form.get("name", "").strip(), form.get("supplier", "").strip()
    if not code or not name or not supplier:
        return None, "Code, name and supplier are required."
    owner_kind, owner = find_code(prices, code)
    if owner is not None and owner != editing:          # another item (not the one being changed)
        return None, f"Code {code} is already used by a {owner_kind} ({owner['name']})."

    if kind != "ticket":
        price = num(form.get("price"))
        if price is None or price < 0:
            return None, "Price must be 0 or more."
        return {"id": editing["id"] if editing else new_id(), "code": code, "name": name,
                "supplier": supplier, "price": round2(price)}, None

    adult = num(form.get("adultPrice"))
    child = adult if form.get("childPrice", "").strip() == "" else num(form.get("childPrice"))
    if adult is None or adult < 0:
        return None, "Adult price must be 0 or more."
    if child is None or child < 0:
        return None, "Child price must be 0 or more (or leave it empty to use the adult price)."
    if not is_date(form.get("validUntil", "")):
        return None, "Valid until must be a date like 2026-12-31."
    return {"code": code, "name": name, "supplier": supplier, "adultPrice": round2(adult), "childPrice": round2(child),
            "price": round2(adult), "validUntil": form["validUntil"], "confirmedAt": today()}, None


# =============================================================== quotes: lines and totals

def per_person(line):
    """Tickets and meals have an adult and a child price. Transport and guides have qty x price."""
    return line.get("type") in ("ticket", "meal")


def line_total(line):
    if per_person(line):
        return round2(num0(line.get("adults")) * num0(line.get("adultPrice"))
                      + num0(line.get("children")) * num0(line.get("childPrice")))
    return round2(num0(line.get("qty")) * num0(line.get("unitPrice")))


def blank_draft(settings):
    return {"id": None, "quoteNumber": None, "clientName": "", "date": today(), "adults": 2, "children": 0,
            "notes": "", "serviceCharge": round2(settings.get("defaultServiceCharge") or 0), "itemised": True,
            "days": [{"date": "", "lines": []}], "hotels": [], "group": False, "additional": []}


def days_of(q):
    """The quote's days. Very old quotes had no days, only flat ticket/transport lists with dates:
    those are grouped into days here."""
    if q.get("days"):
        return q["days"]
    by_date = {}
    for t in q.get("tickets") or []:
        by_date.setdefault(t.get("travelDate") or t.get("date") or "", []).append({
            "type": "ticket", "code": t.get("code"), "name": t.get("name"), "supplier": t.get("supplier"),
            "adults": t.get("adults", t.get("pax")), "children": t.get("children") or 0,
            "adultPrice": t.get("adultPrice", t.get("unitPrice")), "childPrice": t.get("childPrice", t.get("unitPrice"))})
    for t in q.get("transport") or []:
        by_date.setdefault(t.get("travelDate") or t.get("date") or "", []).append({
            "type": "transport", "code": t.get("code") or "", "description": t.get("description"),
            "supplier": t.get("supplier"), "qty": t.get("qty"), "unitPrice": t.get("unitPrice")})
    for lines in by_date.values():
        for line in lines:
            line["total"] = line_total(line)
    return [{"date": d, "lines": by_date[d]} for d in sorted(by_date)] or [{"date": "", "lines": []}]


def draft_from_quote(q):
    """A saved quote -> a draft to edit."""
    q = copy.deepcopy(q)
    d = {key: q.get(key) for key in ("id", "quoteNumber", "clientName", "date", "adults", "children", "notes",
                                     "serviceCharge", "createdBy", "createdAt")}
    d.update(itemised=q.get("itemised") is not False, days=days_of(q),
             hotels=q.get("hotels") or [], group=q.get("quoteType") == "group", additional=q.get("additionalCharges") or [])
    return d


def line_from_price_list(item, kind, draft):
    """A new quote line for a price list item (the prices are copied, so they can be changed per quote)."""
    if kind == "ticket":
        return {"type": "ticket", "code": item["code"], "name": item["name"], "supplier": item["supplier"],
                "adults": whole(draft["adults"]) or 0, "children": whole(draft["children"]) or 0,
                "adultPrice": adult_price(item), "childPrice": child_price(item)}
    return {"type": kind, "code": item.get("code") or "", "description": item["name"], "supplier": item["supplier"],
            "qty": 1, "unitPrice": round2(item["price"])}


def totals(d):
    """Every subtotal of a draft, and the total."""
    sums = {"ticket": 0.0, "transport": 0.0, "meal": 0.0, "guide": 0.0}
    for day in d["days"]:
        for line in day["lines"]:
            sums[line["type"] if line.get("type") in sums else "transport"] += line_total(line)
    t = {"tickets": sums["ticket"], "transport": sums["transport"], "meals": sums["meal"], "guides": sums["guide"],
         "hotel": sum(num0(h.get("amount")) for h in d["hotels"]),
         "additional": sum(num0(a.get("amount")) for a in d["additional"]) if d.get("group") else 0,
         "service": num0(d.get("serviceCharge"))}
    t = {key: round2(value) for key, value in t.items()}
    t["total"] = round2(sum(t.values()))
    return t


def check_quote(d, prices):
    """The checks before saving. Returns (errors, warnings).
    Errors stop the quote from being saved; warnings are only shown."""
    errors, warnings = [], []
    if not str(d["clientName"]).strip():
        errors.append("Enter the client name.")
    if not is_date(d["date"]):
        errors.append("Enter the quote date, like 2026-12-31.")
    a, c = whole(d["adults"]), whole(d["children"])
    if a is None or a < 0 or c is None or c < 0:
        errors.append("Adults and children must be whole numbers (0 or more).")
    elif a + c < 1:
        errors.append("Enter at least 1 adult or child.")
    if not is_money(d["serviceCharge"]):
        errors.append("Profit must be 0 or more.")
    if not any(day["lines"] for day in d["days"]) and not d["hotels"]:
        errors.append("Add at least one ticket, transport line or hotel.")

    seen = {}
    for di, day in enumerate(d["days"], start=1):
        if not is_date(day.get("date") or ""):
            errors.append(f"Day {di}: enter the date.")
        elif day["date"] in seen:
            warnings.append(f"Day {di} has the same date as Day {seen[day['date']]}.")
        else:
            seen[day["date"]] = di
        if not day["lines"] and len(d["days"]) > 1:
            errors.append(f"Day {di} has nothing on it. Add a line or remove the day.")
        for line in day["lines"]:
            name = f"Day {di}, {line.get('code') or line.get('meal') or line.get('description') or line['type']}"
            if not str(line.get("supplier") or "").strip():
                errors.append(f"{name}: enter the supplier.")
            if per_person(line):
                la, lc = whole(line.get("adults")), whole(line.get("children"))
                if la is None or la < 0 or lc is None or lc < 0:
                    errors.append(f"{name}: adults and children must be whole numbers.")
                elif la + lc < 1:
                    errors.append(f"{name}: needs at least 1 adult or child.")
                if not is_money(line.get("adultPrice")) or not is_money(line.get("childPrice")):
                    errors.append(f"{name}: prices must be 0 or more.")
            else:
                if not str(line.get("description") or "").strip():
                    errors.append(f"{name}: enter a description.")
                if (whole(line.get("qty")) or 0) < 1:
                    errors.append(f"{name}: quantity must be a whole number, 1 or more.")
                if not is_money(line.get("unitPrice")):
                    errors.append(f"{name}: price must be 0 or more.")
            if line["type"] == "ticket":
                _check_ticket(line, name, prices, errors, warnings)

    for hi, h in enumerate(d["hotels"], start=1):
        if not str(h.get("description") or "").strip():
            errors.append(f"Hotel {hi}: enter the hotel name.")
        if not is_money(h.get("amount")):
            errors.append(f"Hotel {hi}: amount must be 0 or more.")
    return errors, warnings


def _check_ticket(line, name, prices, errors, warnings):
    """Is the ticket still in the price list, not expired, and at the list price?"""
    kind, t = find_code(prices, line.get("code"))
    if kind != "ticket":
        errors.append(f"{name} is no longer in the price list.")
        return
    level, text = ticket_status(t)
    if level == "bad":
        errors.append(f"{name}: the price expired on {nice_date(t['validUntil'])}. Update it in the price list.")
    elif text == "Confirm for this month":
        warnings.append(f"{name}: the price has not been confirmed this month.")
    if is_money(line.get("adultPrice")) and round2(line["adultPrice"]) != adult_price(t):
        warnings.append(f"{name}: adult price is {fmt(line['adultPrice'])} here, the price list says {fmt(adult_price(t))}.")
    if num0(line.get("children")) and is_money(line.get("childPrice")) and round2(line["childPrice"]) != child_price(t):
        warnings.append(f"{name}: child price is {fmt(line['childPrice'])} here, the price list says {fmt(child_price(t))}.")


# =============================================================== quotes: saving

def next_quote_number(quotes, day, agent):
    """Q-20261128-AG01-001: the date, the agent code, then 001, 002... for that agent and day.
    The agent code is in it so two agents working offline can never pick the same number."""
    prefix = f"Q-{day.replace('-', '')}-{agent}-"
    used = [int(q["quoteNumber"][len(prefix):]) for q in quotes
            if re.fullmatch(re.escape(prefix) + r"\d+", q.get("quoteNumber") or "")]
    return prefix + f"{max(used, default=0) + 1:03d}"


def build_quote(d, settings):
    """The draft -> the quote record that gets saved (without id, number and times).
    It also has flat lists of tickets/transport/meals/guides with travel dates, which the
    website's supplier report reads."""
    t = totals(d)
    days, flat = [], {"ticket": [], "transport": [], "meal": [], "guide": []}
    for day in d["days"]:
        lines = []
        for l in day["lines"]:
            kind = l["type"] if l.get("type") in flat else "transport"
            supplier, total = str(l.get("supplier") or "").strip(), line_total(l)
            if per_person(l):
                row = {"type": kind, **({"code": l.get("code"), "name": l.get("name")} if kind == "ticket"
                                        else {"meal": l.get("meal"), "description": str(l.get("description") or "").strip()}),
                       "supplier": supplier, "adults": whole(l.get("adults")) or 0,
                       "children": whole(l.get("children")) or 0, "adultPrice": round2(l.get("adultPrice")),
                       "childPrice": round2(l.get("childPrice")), "total": total}
                pax = row["adults"] + row["children"]
                extra = {"pax": pax}
                if kind == "ticket":
                    extra["unitPrice"] = round2(row["total"] / pax) if pax else 0
            else:
                row = {"type": kind, "code": l.get("code") or "", "description": str(l.get("description") or "").strip(),
                       "supplier": supplier, "qty": whole(l.get("qty")) or 0,
                       "unitPrice": round2(l.get("unitPrice")), "total": total}
                extra = {"date": day["date"]} if kind == "transport" else {}
            lines.append(row)
            flat_row = {k: v for k, v in row.items() if k != "type"}
            flat_row.update(travelDate=day["date"], **extra)
            flat[kind].append(flat_row)
        days.append({"date": day["date"], "lines": lines})

    def money_rows(rows):
        return [{"description": str(r.get("description") or "").strip(), "supplier": str(r.get("supplier") or "").strip(),
                 "amount": round2(r.get("amount"))} for r in rows]

    return {"clientName": d["clientName"].strip(), "adults": whole(d["adults"]), "children": whole(d["children"]),
            "date": d["date"], "notes": str(d.get("notes") or "").strip(), "currency": settings.get("currency", "SGD"),
            "serviceCharge": t["service"], "itemised": bool(d["itemised"]), "days": days,
            "hotels": money_rows(d["hotels"]), "quoteType": "group" if d.get("group") else "normal",
            "additionalCharges": money_rows(d["additional"]) if d.get("group") else [],
            "tickets": flat["ticket"], "transport": flat["transport"], "meals": flat["meal"], "guides": flat["guide"],
            "subtotalTickets": t["tickets"], "subtotalTransport": t["transport"], "subtotalMeals": t["meals"],
            "subtotalGuides": t["guides"], "subtotalHotel": t["hotel"], "subtotalAdditional": t["additional"],
            "total": t["total"]}


def line_label(line, quote):
    """How a line is described on the PDF and on screen, e.g. 'City tour (2 A+1C)' or 'Transfer x 2'."""
    if line["type"] == "ticket":
        text = line.get("name") or ""
    elif line["type"] == "meal":
        text = " - ".join(x for x in (line.get("meal"), line.get("description")) if x)
    elif line["type"] == "guide":
        text = "Guide - " + (line.get("description") or "")
    else:
        text = line.get("description") or ""
    if per_person(line):
        if (whole(line.get("adults")), whole(line.get("children"))) != (whole(quote.get("adults")), whole(quote.get("children"))):
            text += f" ({pax_text(line.get('adults'), line.get('children'))})"
    elif (whole(line.get("qty")) or 0) > 1:
        text += f" x {whole(line['qty'])}"
    return text


# =============================================================== supplier report

def report_lines(quotes, date_from, date_to):
    """Every line bought from a supplier with a travel date from date_from to date_to.

    Supplier invoices go by travel date, so each line uses its day's date. Hotels and group
    charges have no date, so they use the first day of the trip. Totals are in cents, so
    adding up hundreds of lines never drifts by a cent."""
    out = []
    for q in quotes:
        days = [d for d in days_of(q) if is_date(d.get("date") or "")]
        first_day = min((d["date"] for d in days), default=q.get("date", ""))
        rows = []
        for day in days:
            for l in day["lines"]:
                rows.append((day["date"], l["type"].capitalize(), l.get("code") or "", line_label(l, q), l))
        for h in q.get("hotels") or []:
            rows.append((first_day, "Hotel", "", h.get("description") or "", h))
        if q.get("quoteType") == "group":   # group charges count only when they have a supplier
            rows += [(first_day, "Additional", "", a.get("description") or "", a)
                     for a in q.get("additionalCharges") or [] if (a.get("supplier") or "").strip()]
        for travel_date, kind, code, item, l in rows:
            if not (date_from <= travel_date <= date_to):
                continue
            total = l.get("total", l.get("amount", 0))
            qty = (whole(l.get("adults")) or 0) + (whole(l.get("children")) or 0) if per_person(l) else (whole(l.get("qty")) or 1)
            out.append({"supplier": (l.get("supplier") or "").strip() or "(No supplier set)", "type": kind,
                        "travelDate": travel_date, "quoteNumber": q.get("quoteNumber", ""), "client": q.get("clientName", ""),
                        "code": code, "item": item, "qty": qty, "cents": round(num0(total) * 100)})
    out.sort(key=lambda r: (r["supplier"].lower(), r["travelDate"], r["quoteNumber"]))
    return out


def report_by_supplier(lines):
    """{supplier: total in cents}, in the same order as the lines."""
    sums = {}
    for r in lines:
        sums[r["supplier"]] = sums.get(r["supplier"], 0) + r["cents"]
    return sums


def write_csv(lines, path):
    """Save the report as a CSV file that opens in Excel or Numbers."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: Excel reads it as UTF-8
        w = csv.writer(f)
        w.writerow(["Supplier", "Type", "Travel date", "Quote no", "Client", "Code", "Item", "Qty", "Total"])
        for r in lines:
            cells = [r["supplier"], r["type"], r["travelDate"], r["quoteNumber"], r["client"], r["code"], r["item"],
                     r["qty"], f"{r['cents'] / 100:.2f}"]
            # Text starting with = + - @ could run as a formula in a spreadsheet: put ' in front.
            w.writerow(["'" + c if isinstance(c, str) and c[:1] in "=+-@" else c for c in cells])
