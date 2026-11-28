"""Travel quotes: the totals, the checks before saving, and the changes made on the quote page.

The quote being edited is called the *draft*. It is a plain dict:
  {
    id, quoteNumber,            None until the quote is saved the first time
    clientName, adults, children, date, notes,
    serviceCharge,              the flat profit / service charge for the whole quote
    itemised,                   True = show a total on every line of the PDF
    group,                      True for a group quote (allows additional charges)
    days: [ {date, lines: [line, ...]}, ... ],
    hotels: [ {description, supplier, amount}, ... ],
    additional: [ {description, supplier, amount}, ... ]     (group quotes only)
  }
A line is one of:
  {type: "ticket",    code, name, supplier, adults, children, adultPrice, childPrice}
  {type: "transport", code, description, supplier, qty, unitPrice}
  {type: "meal",      meal ("Breakfast"/"Lunch"/"Dinner"), description, supplier, adults, children, adultPrice, childPrice}
  {type: "guide",     code, description, supplier, qty, unitPrice}

When saved, build_quote() turns the draft into the saved record (same shape the website saves,
see ../DATA_FORMAT.md), including flat lists of tickets/transport/meals/guides with their travel
dates for the supplier report.
"""
import copy
import re

from helpers import (round2, fmt_num, fmt_date, today, is_valid_date, is_whole, is_money,
                     num_or_zero, as_int, add_days)
import prices as pl

MEALS = ["Breakfast", "Lunch", "Dinner"]
COMMON_EXTRAS = ["Coach / bus", "Tour leader", "Entrance permits", "Tips", "Group handling fee", "Porterage"]


def per_pax(line):
    """Tickets and meals are priced per adult and per child; the rest by quantity."""
    return line.get("type") in ("ticket", "meal")


# ---------------------------------------------------------------- new / opened drafts

def blank_draft(settings):
    return {"id": None, "quoteNumber": None, "clientName": "", "adults": 2, "children": 0,
            "date": today(), "notes": "", "serviceCharge": round2(settings.get("defaultServiceCharge") or 0),
            "itemised": True, "group": False, "days": [{"date": "", "lines": []}], "hotels": [], "additional": []}


def draft_from_quote(q):
    """Turn a saved quote back into a draft for editing (also converts very old quotes)."""
    q = copy.deepcopy(q)
    base = {"id": q.get("id"), "quoteNumber": q.get("quoteNumber"), "clientName": q.get("clientName") or "",
            "adults": q.get("adults", 1), "children": q.get("children") or 0, "date": q.get("date") or today(),
            "notes": q.get("notes") or "", "serviceCharge": q.get("serviceCharge", 0),
            "itemised": q.get("itemised") is not False, "group": q.get("quoteType") == "group",
            "hotels": q.get("hotels") or [], "additional": q.get("additionalCharges") or [],
            "createdBy": q.get("createdBy") or ""}
    if isinstance(q.get("days"), list):
        base["days"] = q["days"] or [{"date": "", "lines": []}]
        for day in base["days"]:
            for line in day["lines"]:
                line.pop("total", None)
        return base
    # Very old quotes had flat ticket/transport lists with dates: group them into days.
    by_date = {}
    for l in q.get("tickets") or []:
        d = l.get("travelDate") or l.get("date") or ""
        by_date.setdefault(d, []).append({"type": "ticket", "code": l.get("code"), "name": l.get("name"),
            "supplier": l.get("supplier"), "adults": l.get("adults", l.get("pax")), "children": l.get("children") or 0,
            "adultPrice": l.get("adultPrice", l.get("unitPrice")), "childPrice": l.get("childPrice", l.get("unitPrice"))})
    for l in q.get("transport") or []:
        d = l.get("travelDate") or l.get("date") or ""
        by_date.setdefault(d, []).append({"type": "transport", "code": l.get("code") or "", "description": l.get("description"),
            "supplier": l.get("supplier"), "qty": l.get("qty"), "unitPrice": l.get("unitPrice")})
    base["days"] = [{"date": d, "lines": by_date[d]} for d in sorted(by_date)] or [{"date": "", "lines": []}]
    return base


def clean_draft(d, settings):
    """Fill in anything missing from a draft that came from the browser."""
    out = blank_draft(settings)
    out.update({k: v for k, v in (d or {}).items() if k in out or k == "createdBy"})
    for key in ("days", "hotels", "additional"):
        if not isinstance(out[key], list):
            out[key] = []
    if not out["days"]:
        out["days"] = [{"date": "", "lines": []}]
    for day in out["days"]:
        day.setdefault("date", "")
        day["lines"] = [l for l in day.get("lines") or [] if isinstance(l, dict)]
    out["group"] = bool(out["group"])
    return out


# ---------------------------------------------------------------- totals

def line_total(line):
    if per_pax(line):
        return round2(num_or_zero(line.get("adults")) * num_or_zero(line.get("adultPrice"))
                      + num_or_zero(line.get("children")) * num_or_zero(line.get("childPrice")))
    return round2(num_or_zero(line.get("qty")) * num_or_zero(line.get("unitPrice")))


def calc(d):
    """All the totals of a draft."""
    sums = {"ticket": 0.0, "transport": 0.0, "meal": 0.0, "guide": 0.0}
    for day in d["days"]:
        for line in day["lines"]:
            kind = line.get("type") if line.get("type") in sums else "transport"
            sums[kind] += line_total(line)
    hotel = sum(num_or_zero(h.get("amount")) for h in d["hotels"])
    additional = sum(num_or_zero(h.get("amount")) for h in d["additional"]) if d["group"] else 0
    t = {"tickets": round2(sums["ticket"]), "transport": round2(sums["transport"]), "meals": round2(sums["meal"]),
         "guides": round2(sums["guide"]), "hotel": round2(hotel), "additional": round2(additional),
         "service": round2(num_or_zero(d.get("serviceCharge")))}
    t["total"] = round2(sum(t.values()))
    return t


# ---------------------------------------------------------------- checks before saving

def validate(d, prices):
    """Returns (errors, warnings, bad_fields).

    errors stop the quote from being saved; warnings are only shown.
    bad_fields are paths like "days.0.lines.1.adults" so the page can outline those boxes in red.
    """
    errors, warnings, bad = [], [], []

    def err(text, path=None):
        errors.append(text)
        if path:
            bad.append(path)

    if not str(d["clientName"]).strip():
        err("Enter the client name.", "clientName")
    if not is_whole(d["adults"], 0):
        err("Adults must be a whole number.", "adults")
    if not is_whole(d["children"], 0):
        err("Children must be a whole number (0 if none).", "children")
    if is_whole(d["adults"], 0) and is_whole(d["children"], 0) and num_or_zero(d["adults"]) + num_or_zero(d["children"]) < 1:
        err("Enter at least 1 adult or child.", "adults")
    if not is_valid_date(d["date"]):
        err("Enter a valid quote date.", "date")
    line_count = sum(len(day["lines"]) for day in d["days"])
    if not line_count and not d["hotels"] and not (d["group"] and d["additional"]):
        err("Add at least one attraction, transport line or hotel.")
    if not is_money(d["serviceCharge"]):
        err("Profit must be 0 or more.", "serviceCharge")

    seen_dates = {}
    for di, day in enumerate(d["days"]):
        dn = f"Day {di + 1}"
        if not is_valid_date(day.get("date") or ""):
            err(f"{dn}: enter the date.", f"days.{di}.date")
        elif day["date"] in seen_dates:
            warnings.append(f"{dn} has the same date as Day {seen_dates[day['date']]}.")
        else:
            seen_dates[day["date"]] = di + 1
        if not day["lines"] and (len(d["days"]) > 1 or not d["hotels"]):
            err(f"{dn} has nothing on it. Add a line or remove the day.")

        for li, line in enumerate(day["lines"]):
            p = f"days.{di}.lines.{li}."
            kind = line.get("type")
            if kind in ("ticket", "meal"):
                name = f"{dn}, {line.get('code')}" if kind == "ticket" else f"{dn}, {str(line.get('meal') or 'meal').lower()}"
                if kind == "meal" and not str(line.get("supplier") or "").strip():
                    err(f"{name}: enter the supplier.", p + "supplier")
                if not is_whole(line.get("adults"), 0):
                    err(f"{name}: adults must be a whole number.", p + "adults")
                if not is_whole(line.get("children"), 0):
                    err(f"{name}: children must be a whole number.", p + "children")
                if (is_whole(line.get("adults"), 0) and is_whole(line.get("children"), 0)
                        and num_or_zero(line["adults"]) + num_or_zero(line["children"]) < 1):
                    err(f"{name}: needs at least 1 adult or child.", p + "adults")
                if not is_money(line.get("adultPrice")):
                    err(f"{name}: adult price must be 0 or more.", p + "adultPrice")
                if not is_money(line.get("childPrice")):
                    err(f"{name}: child price must be 0 or more.", p + "childPrice")
                if kind == "ticket":
                    _check_ticket_against_price_list(line, name, prices, errors, warnings)
            else:
                name = f"{dn}, guide" if kind == "guide" else f"{dn}, transport line {li + 1}"
                if kind != "guide" and not str(line.get("description") or "").strip():
                    err(f"{name}: enter a description.", p + "description")
                if not str(line.get("supplier") or "").strip():
                    err(f"{name}: enter the supplier.", p + "supplier")
                if not is_whole(line.get("qty"), 1):
                    err(f"{name}: quantity must be 1 or more.", p + "qty")
                if not is_money(line.get("unitPrice")):
                    err(f"{name}: price must be 0 or more.", p + "unitPrice")

    for i, h in enumerate(d["hotels"]):
        if not str(h.get("description") or "").strip():
            err(f"Hotel {i + 1}: enter the hotel name.", f"hotels.{i}.description")
        if not is_money(h.get("amount")):
            err(f"Hotel {i + 1}: amount must be 0 or more.", f"hotels.{i}.amount")
    if d["group"]:
        for i, h in enumerate(d["additional"]):
            if not str(h.get("description") or "").strip():
                err(f"Additional charge {i + 1}: enter what it is for.", f"additional.{i}.description")
            if not is_money(h.get("amount")):
                err(f"Additional charge {i + 1}: amount must be 0 or more.", f"additional.{i}.amount")
    return errors, warnings, bad


def _check_ticket_against_price_list(line, name, prices, errors, warnings):
    t = pl.find_ticket(prices, line.get("code"))
    if not t:
        errors.append(f"{name} is no longer in the price list.")
        return
    level, text = pl.ticket_status(t)
    if level == "bad":
        errors.append(f"{name} price expired on {fmt_date(t['validUntil'])}. Update it in the price list.")
    elif text == "Confirm for this month":
        warnings.append(f"{name} price has not been confirmed this month.")
    if is_money(line.get("adultPrice")) and round2(line["adultPrice"]) != pl.adult_price(t):
        warnings.append(f"{name} adult price is {fmt_num(line['adultPrice'])} here; the price list says {fmt_num(pl.adult_price(t))}.")
    if num_or_zero(line.get("children")) > 0 and is_money(line.get("childPrice")) and round2(line["childPrice"]) != pl.child_price(t):
        warnings.append(f"{name} child price is {fmt_num(line['childPrice'])} here; the price list says {fmt_num(pl.child_price(t))}.")


def edited_prices(d, prices):
    """Paths of ticket price boxes that differ from the price list (shown in a different colour)."""
    out = []
    for di, day in enumerate(d["days"]):
        for li, line in enumerate(day["lines"]):
            t = pl.find_ticket(prices, line.get("code")) if line.get("type") == "ticket" else None
            if not t:
                continue
            for field, list_price in (("adultPrice", pl.adult_price(t)), ("childPrice", pl.child_price(t))):
                if line.get(field) not in ("", None) and round2(line[field]) != list_price:
                    out.append(f"days.{di}.lines.{li}.{field}")
    return out


# ---------------------------------------------------------------- changes made with the buttons

def apply_action(d, action, prices):
    """Make one change to the draft (add a line, remove a day...). Returns (message, kind, focus).

    kind is "ok" or "err" for the message colour; focus is the path of the box to put the cursor in.
    """
    name = action.get("name")
    day_i = int(action.get("day", 0) or 0)
    i = int(action.get("index", 0) or 0)
    days = d["days"]
    lines = days[day_i]["lines"] if 0 <= day_i < len(days) else None

    if name == "add_code":
        return _add_by_code(d, day_i, action.get("code") or "", prices)
    if name == "add_transport":
        item = next((t for t in prices["transport"] if t["id"] == action.get("id")), None)
        if item:
            lines.append(_transport_line(item))
            return None, None, f"days.{day_i}.lines.{len(lines) - 1}.unitPrice"
        lines.append({"type": "transport", "code": "", "description": "", "supplier": "", "qty": 1, "unitPrice": ""})
        return None, None, f"days.{day_i}.lines.{len(lines) - 1}.description"
    if name == "add_meal":
        lines.append({"type": "meal", "meal": action.get("meal") if action.get("meal") in MEALS else "Lunch",
                      "description": "", "supplier": "", "adults": as_int(d["adults"]), "children": as_int(d["children"]),
                      "adultPrice": "", "childPrice": ""})
        return None, None, f"days.{day_i}.lines.{len(lines) - 1}.description"
    if name == "add_guide":
        lines.append({"type": "guide", "code": "", "description": "", "supplier": "", "qty": 1, "unitPrice": ""})
        return None, None, f"days.{day_i}.lines.{len(lines) - 1}.description"
    if name == "del_line" and lines and 0 <= i < len(lines):
        lines.pop(i)
    elif name == "up" and lines and 0 < i < len(lines):
        lines[i - 1], lines[i] = lines[i], lines[i - 1]
    elif name == "down" and lines and 0 <= i < len(lines) - 1:
        lines[i + 1], lines[i] = lines[i], lines[i + 1]
    elif name == "add_day":
        last = days[-1]["date"] if days else ""
        days.append({"date": add_days(last, 1) if is_valid_date(last) else "", "lines": []})
        return None, None, f"code.{len(days) - 1}"
    elif name == "del_day" and 0 <= day_i < len(days):
        days.pop(day_i)
        if not days:
            days.append({"date": "", "lines": []})
    elif name == "add_hotel":
        d["hotels"].append({"description": "", "supplier": "", "amount": ""})
        return None, None, f"hotels.{len(d['hotels']) - 1}.description"
    elif name == "del_hotel" and 0 <= i < len(d["hotels"]):
        d["hotels"].pop(i)
    elif name == "add_extra":
        d["additional"].append({"description": "", "supplier": "", "amount": ""})
        return None, None, f"additional.{len(d['additional']) - 1}.description"
    elif name == "del_extra" and 0 <= i < len(d["additional"]):
        d["additional"].pop(i)
    elif name == "set_pax":
        _change_group_pax(d, action.get("field"), action.get("old"))
    return None, None, None


def _transport_line(t):
    return {"type": "transport", "code": t.get("code") or "", "description": t["name"], "supplier": t["supplier"],
            "qty": 1, "unitPrice": round2(t["price"])}


def _add_by_code(d, day_i, raw, prices):
    """Like a till: type a ticket, transfer or guide code (or a unique part of its name)."""
    raw = raw.strip()
    if not raw:
        return None, None, None
    lines = d["days"][day_i]["lines"]
    focus = f"code.{day_i}"
    kind, item = pl.code_owner(prices, raw)
    if item is None:
        q = raw.lower()
        matches = ([("ticket", t) for t in prices["tickets"] if q in t["name"].lower()]
                   + [("transfer", t) for t in prices["transport"] if q in t["name"].lower()]
                   + [("guide", t) for t in prices["guides"] if q in ("guide " + t["name"]).lower()])
        if len(matches) != 1:
            text = f'More than one item matches "{raw}". Type the code.' if matches else f'No ticket, transfer or guide with code "{raw}".'
            return text, "err", focus
        kind, item = matches[0]
    if kind == "transfer":
        lines.append(_transport_line(item))
        return f"Added {item.get('code') + ' — ' if item.get('code') else ''}{item['name']}.", "ok", focus
    if kind == "guide":
        lines.append({"type": "guide", "code": item["code"], "description": item["name"], "supplier": item["supplier"],
                      "qty": 1, "unitPrice": round2(item["price"])})
        return f"Added guide {item['code']} — {item['name']}.", "ok", focus
    level, text = pl.ticket_status(item)
    if level == "bad":
        return f"{item['code']} price expired on {fmt_date(item['validUntil'])}. Update it in the price list first.", "err", focus
    lines.append({"type": "ticket", "code": item["code"], "name": item["name"], "supplier": item["supplier"],
                  "adults": as_int(d["adults"]), "children": as_int(d["children"]),
                  "adultPrice": pl.adult_price(item), "childPrice": pl.child_price(item)})
    return f"Added {item['code']} — {item['name']}." + (f" ({text})" if level == "warn" else ""), "ok", focus


def _change_group_pax(d, field, old):
    """The group's adults or children changed: lines that still had the old number follow it."""
    if field not in ("adults", "children"):
        return
    for day in d["days"]:
        for line in day["lines"]:
            if per_pax(line) and line.get(field) not in ("", None) and num_or_zero(line[field]) == num_or_zero(old):
                line[field] = d[field]


# ---------------------------------------------------------------- saving

def next_quote_number(quotes, date, agent):
    """Q-20261128-AG01-001: date, agent code, then 001, 002... for that agent on that day.

    The agent code is in the number so two agents working offline never pick the same one.
    """
    prefix = f"Q-{date.replace('-', '')}-{agent}-"
    used = [int(m.group(1)) for q in quotes
            for m in [re.fullmatch(re.escape(prefix) + r"(\d+)", q.get("quoteNumber") or "")] if m]
    return prefix + f"{max(used, default=0) + 1:03d}"


def build_quote(d, settings):
    """The record that gets saved (without id, number and timestamps)."""
    t = calc(d)
    days = []
    for day in d["days"]:
        out_lines = []
        for l in day["lines"]:
            kind = l.get("type")
            if kind in ("ticket", "meal"):
                row = {"type": kind}
                if kind == "ticket":
                    row.update(code=l.get("code"), name=l.get("name"))
                else:
                    row.update(meal=l.get("meal"), description=str(l.get("description") or "").strip())
                row.update(supplier=str(l.get("supplier") or "").strip(), adults=as_int(l.get("adults")),
                           children=as_int(l.get("children")), adultPrice=round2(l.get("adultPrice")),
                           childPrice=round2(l.get("childPrice")), total=line_total(l))
            else:
                row = {"type": "guide" if kind == "guide" else "transport", "code": l.get("code") or "",
                       "description": str(l.get("description") or "").strip(), "supplier": str(l.get("supplier") or "").strip(),
                       "qty": as_int(l.get("qty")), "unitPrice": round2(l.get("unitPrice")), "total": line_total(l)}
            out_lines.append(row)
        days.append({"date": day["date"], "lines": out_lines})

    # Flat copies with travel dates, read by the supplier report.
    tickets, transport, meals, guides = [], [], [], []
    for day in days:
        for l in day["lines"]:
            if l["type"] == "ticket":
                pax = l["adults"] + l["children"]
                tickets.append({"code": l["code"], "name": l["name"], "supplier": l["supplier"], "travelDate": day["date"],
                                "adults": l["adults"], "children": l["children"], "adultPrice": l["adultPrice"],
                                "childPrice": l["childPrice"], "pax": pax, "unitPrice": round2(l["total"] / pax) if pax else 0,
                                "total": l["total"]})
            elif l["type"] == "meal":
                meals.append({"meal": l["meal"], "description": l["description"], "supplier": l["supplier"],
                              "travelDate": day["date"], "adults": l["adults"], "children": l["children"],
                              "adultPrice": l["adultPrice"], "childPrice": l["childPrice"],
                              "pax": l["adults"] + l["children"], "total": l["total"]})
            elif l["type"] == "guide":
                guides.append({"code": l["code"], "description": l["description"], "supplier": l["supplier"],
                               "travelDate": day["date"], "qty": l["qty"], "unitPrice": l["unitPrice"], "total": l["total"]})
            else:
                transport.append({"code": l["code"], "description": l["description"], "supplier": l["supplier"],
                                  "date": day["date"], "travelDate": day["date"], "qty": l["qty"],
                                  "unitPrice": l["unitPrice"], "total": l["total"]})

    def money_rows(rows):
        return [{"description": str(h.get("description") or "").strip(), "supplier": str(h.get("supplier") or "").strip(),
                 "amount": round2(h.get("amount"))} for h in rows]

    return {
        "clientName": str(d["clientName"]).strip(), "adults": as_int(d["adults"]), "children": as_int(d["children"]),
        "date": d["date"], "notes": str(d.get("notes") or "").strip(), "currency": settings.get("currency", "SGD"),
        "serviceCharge": t["service"], "itemised": d.get("itemised") is not False,
        "days": days, "hotels": money_rows(d["hotels"]),
        "quoteType": "group" if d["group"] else "normal",
        "additionalCharges": money_rows(d["additional"]) if d["group"] else [],
        "tickets": tickets, "transport": transport, "meals": meals, "guides": guides,
        "subtotalTickets": t["tickets"], "subtotalTransport": t["transport"], "subtotalMeals": t["meals"],
        "subtotalGuides": t["guides"], "subtotalHotel": t["hotel"], "subtotalAdditional": t["additional"],
        "total": t["total"],
    }


def normalise_saved(q):
    """A saved quote in the layout used for the PDF (very old quotes get days added)."""
    if isinstance(q.get("days"), list):
        return q
    out = dict(q)
    out.update(build_quote(clean_draft(draft_from_quote(q), {}), {"currency": q.get("currency", "")}))
    return out


def picker_options(prices):
    """Suggestions for the code box on each day: (code, label)."""
    out = [(t["code"], f"{t['code']} — {t['name']} (A {fmt_num(pl.adult_price(t))} / C {fmt_num(pl.child_price(t))})")
           for t in sorted(prices["tickets"], key=lambda t: t["code"])]
    out += [(t["code"], f"{t['code']} — {t['name']} (transfer {fmt_num(t['price'])})") for t in prices["transport"] if t.get("code")]
    out += [(t["code"], f"{t['code']} — Guide, {t['name']} ({fmt_num(t['price'])})") for t in prices["guides"]]
    return out


def extra_suggestions(quotes):
    names = set(COMMON_EXTRAS)
    for q in quotes:
        names.update(a.get("description", "") for a in q.get("additionalCharges") or [])
    return sorted(n for n in names if n)

