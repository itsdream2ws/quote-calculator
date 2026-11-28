"""Quote Calculator for Mac: the web pages, served on this computer only.

Start it with  python3 app.py  (or double-click "Start Quote Calculator.command"), and it opens
http://127.0.0.1:5055 in your browser.

How the pieces fit together:
  app.py           this file: one function per page or button ("routes")
  quotes.py        travel quote rules: totals, checks, the buttons on the quote page
  invoices.py      proforma invoice rules
  prices.py        price list rules (codes, expiry, monthly confirm)
  report.py        the supplier report
  exports.py       drawing the PDF and PNG
  store.py         the database file on this Mac (works offline)
  sync.py          sending and fetching data to and from Supabase
  supabase_api.py  the actual internet calls to Supabase
  templates/       the HTML of each page (Jinja templates)
  static/          styles.css, editor.js (the small bit of JavaScript), fonts

Saving a quote never needs internet: it is saved on this Mac, then sent to Supabase straight
away if there is a connection, or at the next sync. Changing the price list or settings does
need internet, so every Mac always has the same prices.
"""
import base64
import io
import json
import secrets
import threading
import webbrowser
from urllib.parse import urlencode

from flask import (Flask, Response, flash, jsonify, redirect, render_template, request,
                   send_file, url_for)

import config
import exports
import invoices as inv
import prices as pl
import quotes as qt
import report as rp
import store
import supabase_api as api
import sync
from helpers import (fmt_num, fmt_date, weekday, money, pax_label, today, now_iso, new_id, is_valid_date,
                     month_range, to_number, round2, add_days)

app = Flask(__name__)

DEFAULT_SETTINGS = {"businessName": "Your Business Name", "businessDetails": "", "currency": "SGD",
                    "defaultServiceCharge": 0, "profitDisplay": "service",
                    "footer": "Prices are subject to availability at the time of booking."}


def secret_key():
    """Flask needs a secret to sign its cookies. Made once and kept in the data folder."""
    key = store.get("flask_secret")
    if not key:
        key = secrets.token_hex(32)
        store.put("flask_secret", key)
    return key


app.secret_key = secret_key()


# ---------------------------------------------------------------- shared bits for every page

def settings():
    return {**DEFAULT_SETTINGS, **(store.get("settings") or {})}


def price_list():
    return store.get("prices") or pl.empty_price_list()


def agent():
    return (sync.current_login() or {}).get("agent", "")


@app.template_filter("num")
def _num(n):
    return fmt_num(n or 0)


@app.template_filter("date")
def _date(s):
    return fmt_date(s)


app.jinja_env.globals.update(pax_label=pax_label, weekday=weekday, ticket_status=pl.ticket_status, adult_price=pl.adult_price,
                             child_price=pl.child_price, meals=qt.MEALS, line_total=qt.line_total)


@app.context_processor
def page_globals():
    p = price_list()
    return {"agent": agent(), "brand": settings().get("businessName") or "Quote Calculator",
            "unsent": store.unsent_count(), "last_sync": store.get("last_sync"),
            "price_alerts": sum(1 for t in p["tickets"] if pl.ticket_status(t)[0] != "ok")}


@app.before_request
def only_from_this_app():
    """The app runs on your own Mac. Refuse requests sent by other websites open in the browser."""
    allowed = {f"{config.HOST}:{config.PORT}", f"localhost:{config.PORT}"}
    if request.host not in allowed and not app.testing:
        return Response("Open the app at http://127.0.0.1:%d/" % config.PORT, 403)
    origin = request.headers.get("Origin")
    if request.method == "POST" and origin and origin.split("://", 1)[-1] not in allowed and not app.testing:
        return Response("Blocked: that request came from another website.", 403)


@app.before_request
def require_login():
    if request.endpoint not in ("login", "static") and not sync.current_login():
        return redirect(url_for("login"))


def back(default="quote_page"):
    """Go back to the page the button was on."""
    return redirect(request.referrer or url_for(default))


def online(action, done_message):
    """Run something that needs Supabase (like changing the price list), then refresh the
    price list on this Mac. Shows done_message, or what went wrong."""
    try:
        token = sync.fresh_token()
        action(token)
        store.put("prices", api.download_prices(token))
        flash(done_message, "ok")
        return True
    except api.SupabaseError as e:
        flash(("You are offline. " if e.offline else "") + f"Not saved: {e}", "err")
        return False


# ---------------------------------------------------------------- logging in and syncing

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        code, password = request.form.get("agent", "").strip(), request.form.get("password", "")
        if not code or not password:
            flash("Enter your agent code and password.", "err")
            return render_template("login.html", code=code)
        try:
            session = api.sign_in(code, password)
        except api.SupabaseError as e:
            flash(("Logging in needs internet the first time. " if e.offline else "") + str(e), "err")
            return render_template("login.html", code=code)
        old = sync.current_login()
        if old and old.get("user_id") != session["user_id"] and store.unsent_count():
            flash("Another agent's quotes on this Mac have not been sent yet. Log in as them and sync first.", "err")
            return render_template("login.html", code=code)
        session["agent"] = api.agent_code(session["email"])
        store.put("login", session)
        try:
            sync.sync_now()
            flash("Logged in and synced.", "ok")
        except api.SupabaseError as e:
            flash(f"Logged in, but the sync failed: {e}", "err")
        return redirect(url_for("quote_page"))
    return render_template("login.html", code="")


@app.post("/logout")
def logout():
    if store.unsent_count():
        flash("Some quotes are not sent to Supabase yet. Click Sync now (with internet) before logging out.", "err")
        return back()
    api.sign_out(sync.current_login())
    store.remove("login")
    return redirect(url_for("login"))


@app.post("/sync")
def sync_page():
    try:
        s = sync.sync_now()
        text = f"Synced. Sent {s['sent']}, received {s['received']} new."
        if s["renumbered"]:
            text += " These numbers were already used online, so they were changed: " + ", ".join(s["renumbered"]) + "."
        flash(text, "ok")
    except api.SupabaseError as e:
        flash(("No internet. Your work is saved on this Mac and will be sent at the next sync." if e.offline
               else f"Sync failed: {e}"), "err")
    return back()


def push_one(kind, record):
    """Try to send one saved quote/invoice straight away. Offline is fine: it waits for the next sync."""
    try:
        token = sync.fresh_token()
        row = sync.TABLES[kind][2](record)
        api.upsert(token, sync.TABLES[kind][0], [row], "id")
        store.save_record(kind, record, dirty=False)
        return True
    except api.SupabaseError:
        return False


# ================================================================ TRAVEL QUOTE PAGE

@app.get("/")
def home():
    return redirect(url_for("quote_page"))


@app.get("/quote")
def quote_page():
    s = settings()
    draft, note = None, ""
    if request.args.get("edit"):
        q = store.get_record("quote", request.args["edit"])
        draft = qt.draft_from_quote(q) if q else None
    elif request.args.get("copy"):
        q = store.get_record("quote", request.args["copy"])
        if q:
            draft = qt.draft_from_quote(q)
            draft.update(id=None, quoteNumber=None, createdBy="", date=today())
            note = "Copied. This will save as a new quote."
    restore = draft is None and not request.args.get("new")  # the page may bring back an unsaved draft
    draft = qt.clean_draft(draft or qt.blank_draft(s), s)
    return render_template("quote.html", draft=draft, restore=restore, note=note, **quote_editor_parts(draft))


def quote_editor_parts(draft):
    p = price_list()
    quotes = store.all_records("quote")
    return {"prices": p, "settings": settings(), "codes": qt.picker_options(p),
            "supplier_names": pl.suppliers(p, quotes), "extras": qt.extra_suggestions(quotes)}


def quote_check(draft, show_errors):
    """What the page shows next to the form: totals, problems, line totals."""
    p, s = price_list(), settings()
    t = qt.calc(draft)
    errors, warnings, bad = qt.validate(draft, p)
    cur = s.get("currency", "")
    out = {f"days.{di}.lines.{li}.total": fmt_num(qt.line_total(l))
           for di, day in enumerate(draft["days"]) for li, l in enumerate(day["lines"])}
    out.update({f"days.{di}.subtotal": fmt_num(sum(qt.line_total(l) for l in day["lines"])) if day["lines"] else ""
                for di, day in enumerate(draft["days"])})
    out.update({"tTickets": money(t["tickets"], cur), "tTransport": money(t["transport"], cur),
                "tMeals": money(t["meals"] + t["guides"], cur), "tHotel": money(t["hotel"], cur),
                "tExtra": money(t["additional"], cur), "tGrand": money(t["total"], cur), "mTotal": money(t["total"], cur),
                "tPax": (draft["clientName"] + " · " if draft["clientName"] else "") + pax_label(draft["adults"], draft["children"])
                        + (" · Group" if draft["group"] else "")})
    return {"out": out, "errors": errors if show_errors else [], "warnings": warnings,
            "bad": bad if show_errors else [], "edited": qt.edited_prices(draft, p), "ok": not errors}


@app.post("/quote/check")
def quote_check_route():
    body = request.get_json()
    return jsonify(quote_check(qt.clean_draft(body.get("draft"), settings()), body.get("showErrors")))


@app.post("/quote/action")
def quote_action():
    """A button on the quote page (add a line, remove a day...): change the draft, redraw the form."""
    body = request.get_json()
    draft = qt.clean_draft(body.get("draft"), settings())
    message, kind, focus = qt.apply_action(draft, body.get("action") or {}, price_list())
    html = render_template("_quote_editor.html", draft=draft, **quote_editor_parts(draft))
    return jsonify({"draft": draft, "html": html, "message": message, "kind": kind, "focus": focus,
                    "day": (body.get("action") or {}).get("day"),
                    "check": quote_check(draft, body.get("showErrors"))})


@app.post("/quote/save")
def quote_save():
    s = settings()
    draft = qt.clean_draft(request.get_json().get("draft"), s)
    check = quote_check(draft, True)
    if not check["ok"]:
        return jsonify({"saved": False, "check": check, "message": "Not saved. Fix the highlighted fields."})
    existing = store.get_record("quote", draft["id"]) if draft["id"] else None
    now = now_iso()
    q = {"id": draft["id"] or new_id(),
         "quoteNumber": existing["quoteNumber"] if existing else qt.next_quote_number(store.all_records("quote"), draft["date"], agent())}
    q.update(qt.build_quote(draft, s))
    q.update(createdAt=existing.get("createdAt", now) if existing else now, updatedAt=now,
             createdBy=(existing.get("createdBy") or "") if existing else agent(), updatedBy=agent())
    store.save_record("quote", q)
    sent = push_one("quote", q)
    draft.update(id=q["id"], quoteNumber=q["quoteNumber"])
    return jsonify({"saved": True, "id": q["id"], "number": q["quoteNumber"], "draft": draft, "check": check,
                    "message": f"Saved as {q['quoteNumber']} ({fmt_date(q['date'])})."
                               + ("" if sent else " Offline: it will be sent at the next sync.")})


@app.post("/quote/preview")
def quote_preview():
    """Picture of the quote as it is now, before saving."""
    body = request.get_json()
    s = settings()
    draft = qt.clean_draft(body.get("draft"), s)
    q = {"quoteNumber": draft.get("quoteNumber") or "(not saved yet)", **qt.build_quote(draft, s)}
    return send_file(io.BytesIO(exports.quote_file(q, s, "png", body.get("itemised", True))), mimetype="image/png")


# ================================================================ SAVED QUOTES

@app.get("/quotes")
def saved_quotes():
    search, date_from, date_to = (request.args.get(k, "").strip() for k in ("q", "from", "to"))
    rows = [q for q in store.all_records("quote")
            if (not search or search.lower() in " ".join([q.get("clientName", ""), q.get("quoteNumber", ""),
                                                          q.get("createdBy", "")]).lower())
            and (not date_from or q["date"] >= date_from) and (not date_to or q["date"] <= date_to)]
    rows.sort(key=lambda q: (q["date"], q["quoteNumber"]), reverse=True)
    return render_template("saved.html", rows=rows, search=search, date_from=date_from, date_to=date_to,
                           any_saved=bool(store.all_records("quote")),
                           unsent_ids={r["id"] for r, _ in store.unsent("quote")})


@app.get("/quotes/<qid>")
def quote_view(qid):
    q = store.get_record("quote", qid)
    if not q:
        flash("That quote is not on this Mac.", "err")
        return redirect(url_for("saved_quotes"))
    itemised = request.args.get("itemised", "1" if q.get("itemised", True) else "0") == "1"
    return render_template("view.html", kind="quote", record=q, itemised=itemised,
                           title=f"{q['quoteNumber']} · {q.get('clientName', '')}")


@app.get("/quotes/<qid>/file.<ext>")
def quote_download(qid, ext):
    q = store.get_record("quote", qid)
    if not q or ext not in ("pdf", "png"):
        return Response("Not found", 404)
    itemised = request.args.get("itemised", "1") == "1"
    data = exports.quote_file(qt.normalise_saved(q), settings(), ext, itemised)
    return send_file(io.BytesIO(data), mimetype="application/pdf" if ext == "pdf" else "image/png",
                     as_attachment=request.args.get("download") == "1",
                     download_name=exports.quote_filename(q, itemised, ext))


@app.post("/quotes/<qid>/delete")
def quote_delete(qid):
    q = store.get_record("quote", qid)
    if q:
        store.delete_record("quote", qid)
        try:
            sync.sync_now()
        except api.SupabaseError:
            pass  # offline: the delete is sent at the next sync
        flash(f"Deleted {q['quoteNumber']}.", "ok")
    return redirect(url_for("saved_quotes"))


# ================================================================ PRICE LIST (needs internet)

@app.get("/prices")
def prices_page():
    p = price_list()
    f = {k: request.args.get(k, "").strip().lower() for k in ("tf", "rf", "gf")}
    match = lambda t, text: not text or text in " ".join([t.get("code") or "", t["name"], t["supplier"]]).lower()
    tickets = sorted((t for t in p["tickets"] if match(t, f["tf"])), key=lambda t: t["code"])
    transport = sorted((t for t in p["transport"] if match(t, f["rf"])), key=lambda t: t.get("code") or "~" + t["name"])
    guides = sorted((t for t in p["guides"] if match(t, f["gf"])), key=lambda t: t["code"])
    edit = {"ticket": pl.find_ticket(p, request.args.get("edit_ticket", "")),
            "transport": next((t for t in p["transport"] if t["id"] == request.args.get("edit_transport")), None),
            "guide": next((t for t in p["guides"] if t["id"] == request.args.get("edit_guide")), None)}
    statuses = [pl.ticket_status(t) for t in p["tickets"]]
    return render_template("prices.html", tickets=tickets, transport=transport, guides=guides, edit=edit, f=f,
                           expired=sum(1 for s in statuses if s[0] == "bad"),
                           unconfirmed=sum(1 for s in statuses if s[1] == "Confirm for this month"),
                           supplier_names=pl.suppliers(p))


@app.post("/prices/ticket")
def ticket_save():
    p = price_list()
    editing = request.form.get("editing", "")
    ticket, error = pl.check_ticket_form(p, request.form, editing)
    if error:
        flash(error, "err")
        return redirect(url_for("prices_page", edit_ticket=editing) if editing else url_for("prices_page"))

    def write(token):
        api.upsert(token, "tickets", [api.ticket_to_row(ticket)], "code")
        if editing and editing != ticket["code"]:  # the code was changed: remove the old row
            api.delete(token, "tickets", "code", editing)
    online(write, ("Updated " if editing else "Added ") + ticket["code"] + ".")
    return redirect(url_for("prices_page"))


@app.post("/prices/ticket/<code>/confirm")
def ticket_confirm(code):
    t = pl.find_ticket(price_list(), code)
    if t:
        t = {**t, "confirmedAt": today()}
        online(lambda token: api.upsert(token, "tickets", [api.ticket_to_row(t)], "code"), f"Confirmed {code} for this month.")
    return redirect(url_for("prices_page"))


@app.post("/prices/confirm-all")
def tickets_confirm_all():
    p = price_list()
    ok = [{**t, "confirmedAt": today()} for t in p["tickets"] if pl.ticket_status(t)[0] != "bad"]
    skipped = len(p["tickets"]) - len(ok)
    online(lambda token: api.upsert(token, "tickets", [api.ticket_to_row(t) for t in ok], "code"),
           f"Confirmed {len(ok)} price(s)." + (f" {skipped} expired price(s) skipped: edit them with the new price and date." if skipped else ""))
    return redirect(url_for("prices_page"))


@app.post("/prices/ticket/<code>/delete")
def ticket_delete(code):
    online(lambda token: api.delete(token, "tickets", "code", code), f"Deleted {code}. Saved quotes keep their copy.")
    return redirect(url_for("prices_page"))


@app.post("/prices/<kind>")
def item_save(kind):
    if kind not in ("transport", "guide"):
        return Response("Not found", 404)
    editing = request.form.get("editing", "")
    item, error = pl.check_simple_form(price_list(), request.form, kind, editing)
    if error:
        flash(error, "err")
        return redirect(url_for("prices_page", **({f"edit_{kind}": editing} if editing else {})))
    table = "transport_items" if kind == "transport" else "guide_items"
    online(lambda token: api.upsert(token, table, [api.item_to_row(item)], "id"),
           ("Updated " if editing else "Added ") + item["code"] + ".")
    return redirect(url_for("prices_page"))


@app.post("/prices/<kind>/<item_id>/delete")
def item_delete(kind, item_id):
    if kind not in ("transport", "guide"):
        return Response("Not found", 404)
    table = "transport_items" if kind == "transport" else "guide_items"
    online(lambda token: api.delete(token, table, "id", item_id), "Deleted.")
    return redirect(url_for("prices_page"))


# ================================================================ PROFORMA INVOICE PAGE

def my_letterhead():
    return inv.letterhead(store.get("profiles") or {}, agent(), settings())


@app.get("/invoice")
def invoice_page():
    invoices = store.all_records("invoice")
    profiles = store.get("profiles") or {}
    draft, note = None, ""
    if request.args.get("edit"):
        v = store.get_record("invoice", request.args["edit"])
        draft = inv.draft_from_invoice(v) if v else None
    elif request.args.get("copy"):
        v = store.get_record("invoice", request.args["copy"])
        if v:
            draft = inv.draft_from_invoice(v)
            p = my_letterhead()
            draft.update(id=None, createdBy="", autoNumber=True, date=today(),
                         invoiceNumber=inv.next_invoice_number(invoices, today(), agent()),
                         validUntil=add_days(today(), int(p["validDays"])) if p.get("validDays") else "")
            note = "Copied. This will save as a new invoice."
    restore = draft is None and not request.args.get("new")
    draft = inv.clean_draft(draft or inv.blank_draft(invoices, profiles, agent(), settings()))

    search, date_from, date_to = (request.args.get(k, "").strip() for k in ("q", "from", "to"))
    rows = [v for v in invoices
            if (not search or search.lower() in " ".join([v.get("invoiceNumber", ""), (v.get("billTo") or {}).get("name", ""),
                                                          v.get("reference", ""), v.get("createdBy", "")]).lower())
            and (not date_from or v["date"] >= date_from) and (not date_to or v["date"] <= date_to)]
    rows.sort(key=lambda v: (v["date"], v["invoiceNumber"]), reverse=True)
    return render_template("invoice.html", draft=draft, restore=restore, note=note, logo=my_letterhead()["logo"],
                           titles=inv.TITLES, rows=rows, search=search, date_from=date_from, date_to=date_to,
                           any_saved=bool(invoices), line_amount=inv.line_amount)


def invoice_check(draft, show_errors):
    t = inv.calc(draft)
    errors, bad = inv.validate(draft, store.all_records("invoice"))
    cur = draft["currency"]
    out = {f"items.{i}.amount": fmt_num(inv.line_amount(item)) for i, item in enumerate(draft["items"])}
    n = len(draft["items"])
    out.update({"invSub": money(t["subtotal"], cur), "invTaxAmt": money(t["tax"], cur), "invGrand": money(t["total"], cur),
                "mTotal": money(t["total"], cur),
                "invHeroSub": (draft["clientName"] + " · " if draft["clientName"] else "") + f"{n} line" + ("" if n == 1 else "s")})
    return {"out": out, "errors": errors if show_errors else [], "warnings": [], "bad": bad if show_errors else [],
            "edited": [], "ok": not errors}


@app.post("/invoice/check")
def invoice_check_route():
    body = request.get_json()
    return jsonify(invoice_check(inv.clean_draft(body.get("draft")), body.get("showErrors")))


@app.post("/invoice/action")
def invoice_action():
    body = request.get_json()
    draft = inv.clean_draft(body.get("draft"))
    focus = inv.apply_action(draft, body.get("action") or {}, store.all_records("invoice"), agent())
    html = render_template("_invoice_items.html", draft=draft, line_amount=inv.line_amount)
    return jsonify({"draft": draft, "html": html, "focus": focus, "message": None,
                    "check": invoice_check(draft, body.get("showErrors"))})


@app.post("/invoice/save")
def invoice_save():
    draft = inv.clean_draft(request.get_json().get("draft"))
    check = invoice_check(draft, True)
    if not check["ok"]:
        return jsonify({"saved": False, "check": check, "message": "Not saved. Fix the highlighted fields."})
    existing = store.get_record("invoice", draft["id"]) if draft["id"] else None
    now = now_iso()
    v = {"id": draft["id"] or new_id(), "invoiceNumber": str(draft["invoiceNumber"]).strip(), **inv.build_invoice(draft),
         "createdAt": existing.get("createdAt", now) if existing else now, "updatedAt": now,
         "createdBy": (existing.get("createdBy") or "") if existing else agent(), "updatedBy": agent()}
    store.save_record("invoice", v)
    sent = push_one("invoice", v)
    draft.update(id=v["id"], createdBy=v["createdBy"], autoNumber=False)
    return jsonify({"saved": True, "id": v["id"], "number": v["invoiceNumber"], "draft": draft, "check": check,
                    "message": f"Saved as {v['invoiceNumber']} ({fmt_date(v['date'])})."
                               + ("" if sent else " Offline: it will be sent at the next sync.")})


def logo_of(v):
    """A saved invoice shows the logo of the agent who made it."""
    who = v.get("createdBy") or agent()
    return inv.letterhead(store.get("profiles") or {}, who, settings())["logo"]


@app.post("/invoice/preview")
def invoice_preview():
    body = request.get_json()
    draft = inv.clean_draft(body.get("draft"))
    v = {"invoiceNumber": str(draft["invoiceNumber"] or "").strip() or "(not saved yet)", "createdBy": draft["createdBy"],
         **inv.build_invoice(draft)}
    return send_file(io.BytesIO(exports.invoice_file(v, logo_of(v), "png", body.get("itemised", True))), mimetype="image/png")


@app.post("/invoice/letterhead")
def letterhead_save():
    """'Save as my default letterhead': your next invoices start with these details."""
    d = inv.clean_draft(request.get_json().get("draft"))
    if not str(d["companyName"]).strip():
        return jsonify({"ok": False, "message": "Enter the company name first."})
    rate = to_number(d["taxRate"])
    save_my_profile({"companyName": d["companyName"].strip(), "companyDetails": d["companyDetails"].strip(),
                     "payment": d["payment"].strip(), "terms": d["terms"].strip(), "taxLabel": d["taxLabel"].strip(),
                     "taxRate": rate if rate is not None else 0})
    return jsonify({"ok": True, "message": f"Saved to your login ({agent()}). Your new invoices start with these details."})


def save_my_profile(patch):
    """Change your letterhead here, then send it to Supabase (now, or at the next sync)."""
    profiles = store.get("profiles") or {}
    profiles[agent()] = {**profiles.get(agent(), {}), **patch}
    store.put("profiles", profiles)
    store.put("my_profile_dirty", True)
    try:
        token = sync.fresh_token()
        api.save_my_profile(token, sync.current_login()["user_id"], profiles[agent()])
        store.put("my_profile_dirty", False)
    except api.SupabaseError:
        pass  # sent at the next sync


@app.post("/invoice/logo")
def logo_upload():
    """Shrink the uploaded picture to at most 600 x 240 pixels and save it to your letterhead."""
    from PIL import Image, UnidentifiedImageError
    f = request.files.get("logo")
    if not f or not f.filename:
        flash("Choose a picture first.", "err")
        return redirect(url_for("invoice_page"))
    try:
        img = Image.open(f.stream)
        img.load()
    except (UnidentifiedImageError, OSError):
        flash("That picture could not be opened. Use a PNG, JPG, WebP or GIF.", "err")
        return redirect(url_for("invoice_page"))
    img = img.convert("RGBA")
    img.thumbnail((600, 240))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    data_url = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()
    if len(data_url) > 300_000:  # a big photo-like logo: JPEG on white is far smaller
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.split()[3])
        out = io.BytesIO()
        flat.save(out, format="JPEG", quality=90)
        data_url = "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()
    save_my_profile({"logo": data_url})
    flash(f"Logo saved to your login ({agent()}).", "ok")
    return redirect(url_for("invoice_page"))


@app.post("/invoice/logo/remove")
def logo_remove():
    save_my_profile({"logo": ""})
    flash("Logo removed.", "ok")
    return redirect(url_for("invoice_page"))


@app.get("/invoices/<vid>")
def invoice_view(vid):
    v = store.get_record("invoice", vid)
    if not v:
        flash("That invoice is not on this Mac.", "err")
        return redirect(url_for("invoice_page"))
    itemised = request.args.get("itemised", "1" if v.get("itemised", True) else "0") == "1"
    return render_template("view.html", kind="invoice", record=v, itemised=itemised,
                           title=f"{v['invoiceNumber']} · {(v.get('billTo') or {}).get('name', '')}")


@app.get("/invoices/<vid>/file.<ext>")
def invoice_download(vid, ext):
    v = store.get_record("invoice", vid)
    if not v or ext not in ("pdf", "png"):
        return Response("Not found", 404)
    itemised = request.args.get("itemised", "1") == "1"
    data = exports.invoice_file(v, logo_of(v), ext, itemised)
    return send_file(io.BytesIO(data), mimetype="application/pdf" if ext == "pdf" else "image/png",
                     as_attachment=request.args.get("download") == "1",
                     download_name=exports.invoice_filename(v, itemised, ext))


@app.post("/invoices/<vid>/delete")
def invoice_delete(vid):
    v = store.get_record("invoice", vid)
    if v:
        store.delete_record("invoice", vid)
        try:
            sync.sync_now()
        except api.SupabaseError:
            pass
        flash(f"Deleted {v['invoiceNumber']}.", "ok")
    return redirect(url_for("invoice_page"))


# ================================================================ SUPPLIER REPORT

def report_range():
    month = request.args.get("month") or today()[:7]
    date_from, date_to = request.args.get("from", ""), request.args.get("to", "")
    if not (is_valid_date(date_from) and is_valid_date(date_to)):
        try:
            date_from, date_to = month_range(int(month[:4]), int(month[5:7]))
        except ValueError:
            date_from, date_to = month_range(int(today()[:4]), int(today()[5:7]))
    return month, date_from, date_to


@app.get("/report")
def report_page():
    month, date_from, date_to = report_range()
    supplier = request.args.get("supplier", "")
    try:
        rep = rp.build_report(store.all_records("quote"), date_from, date_to)
    except ValueError as e:
        flash(str(e), "err")
        rep = rp.build_report([], today(), today())
    groups = [g for g in rep["groups"] if not supplier or g["supplier"] == supplier]
    return render_template("report.html", rep=rep, groups=groups, month=month, date_from=date_from, date_to=date_to,
                           supplier=supplier, currency=settings().get("currency") or "SGD", amt=lambda c: f"{c / 100:,.2f}",
                           csv_url=lambda sup: url_for("report_csv") + "?" + urlencode({"from": date_from, "to": date_to, "supplier": sup}),
                           count=len(store.all_records("quote")))


@app.get("/report.csv")
def report_csv():
    _, date_from, date_to = report_range()
    supplier = request.args.get("supplier", "")
    rep = rp.build_report(store.all_records("quote"), date_from, date_to)
    lines = [l for l in rep["lines"] if not supplier or l["supplier"] == supplier]
    slug = "".join(c if c.isalnum() else "-" for c in supplier.lower()).strip("-")
    name = f"supplier-report_{slug + '_' if slug else ''}{date_from}_to_{date_to}.csv"
    return Response(rp.to_csv(lines), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ================================================================ SETTINGS

@app.get("/settings")
def settings_page():
    return render_template("settings.html", s=settings(), login=sync.current_login(), data_file=str(store.db_path()))


@app.post("/settings")
def settings_save():
    service = to_number(request.form.get("defaultServiceCharge"))
    if service is None or service < 0:
        flash("Profit must be 0 or more.", "err")
        return redirect(url_for("settings_page"))
    new = {**settings(), "businessName": request.form.get("businessName", "").strip(),
           "businessDetails": request.form.get("businessDetails", "").strip(),
           "currency": request.form.get("currency", "").strip(), "defaultServiceCharge": round2(service),
           "profitDisplay": request.form.get("profitDisplay", "service"), "footer": request.form.get("footer", "").strip()}
    try:
        api.save_settings(sync.fresh_token(), new)
        store.put("settings", new)
        flash("Settings saved.", "ok")
    except api.SupabaseError as e:
        flash(("You are offline. Settings need internet. " if e.offline else "") + f"Not saved: {e}", "err")
    return redirect(url_for("settings_page"))


@app.post("/settings/password")
def password_change():
    a, b = request.form.get("new", ""), request.form.get("again", "")
    if len(a) < 8:
        flash("Use at least 8 characters.", "err")
    elif a != b:
        flash("The two passwords are different.", "err")
    else:
        try:
            sync.fresh_token()
            api.change_password(sync.current_login(), a)
            flash("Password changed. Use the new one next time you log in.", "ok")
        except api.SupabaseError as e:
            flash(f"Not changed: {e}", "err")
    return redirect(url_for("settings_page"))


@app.get("/backup.json")
def backup():
    data = {"app": "quote-calculator", "version": 1, "exportedAt": now_iso(), "settings": settings(),
            "prices": price_list(), "quotes": store.all_records("quote"), "invoices": store.all_records("invoice")}
    return Response(json.dumps(data, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="quote-calculator-backup-{today()}.json"'})


@app.post("/restore")
def restore():
    """Add a backup file: new quotes/invoices are added, and ones already here are replaced only
    by a newer copy. Nothing is deleted. They are sent to Supabase at the next sync."""
    try:
        d = json.load(request.files["file"].stream)
        assert isinstance(d.get("quotes"), list)
    except Exception:
        flash("That is not a quote calculator backup file.", "err")
        return redirect(url_for("settings_page"))
    added = updated = 0
    renumbered = []
    for kind, key, number_field, next_number in (
            ("quote", "quotes", "quoteNumber", qt.next_quote_number),
            ("invoice", "invoices", "invoiceNumber", inv.next_invoice_number)):
        for rec in d.get(key) or []:
            if not isinstance(rec, dict) or not is_valid_date(rec.get("date") or ""):
                continue
            rec.setdefault("id", new_id())
            here = store.get_record(kind, rec["id"])
            if here:
                if str(rec.get("updatedAt", "")) > str(here.get("updatedAt", "")):
                    rec[number_field] = here[number_field]
                    store.save_record(kind, rec)
                    updated += 1
                continue
            everyone = store.all_records(kind)
            if not rec.get(number_field) or any(x.get(number_field) == rec[number_field] for x in everyone):
                old = rec.get(number_field)
                rec[number_field] = next_number(everyone, rec["date"], agent())
                if old:
                    renumbered.append(f"{old} → {rec[number_field]}")
            store.save_record(kind, rec)
            added += 1
    text = f"Added {added} and updated {updated} quote(s)/invoice(s). Click Sync now to send them."
    if renumbered:
        text += " Numbers already in use were changed: " + ", ".join(renumbered) + "."
    flash(text, "ok")
    return redirect(url_for("settings_page"))


@app.post("/settings/sample")
def sample_prices():
    new = pl.sample_price_list(price_list())

    def write(token):
        api.upsert(token, "tickets", [api.ticket_to_row(t) for t in new["tickets"]], "code")
        api.upsert(token, "transport_items", [api.item_to_row(t) for t in new["transport"]], "id")
        api.upsert(token, "guide_items", [api.item_to_row(t) for t in new["guides"]], "id")
    online(write, "Sample price list added. Have a look in the Price list.")
    return redirect(url_for("settings_page"))


# ================================================================ start

def already_running():
    """True if the app is already open (something is using our port)."""
    import socket
    with socket.socket() as s:
        return s.connect_ex((config.HOST, config.PORT)) == 0


if __name__ == "__main__":
    url = f"http://{config.HOST}:{config.PORT}/"
    if already_running():
        print("The app is already running. Opening it in the browser.")
        webbrowser.open(url)
        raise SystemExit
    print(f"Quote Calculator is running at {url}  (keep this window open; close it to stop the app)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=config.HOST, port=config.PORT, debug=False)
