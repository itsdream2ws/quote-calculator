"""Talking to Supabase (the online database) over the internet.

Supabase has two web addresses we use:
  /auth/v1/...   logging in, refreshing the login, changing the password
  /rest/v1/...   reading and writing the tables (this part of Supabase is called PostgREST)
Every table request carries the agent's own login token, so the database's row level security
decides what is allowed, exactly like the website version.

Table rows <-> the app's objects (same as ../cloud.js in the website):
  tickets          code, name, supplier, adult_price, child_price, valid_until, confirmed_at
  transport_items  id, code, name, supplier, price
  guide_items      id, code, name, supplier, price
  quotes           id, quote_number, quote_date, client_name, total, data (the whole quote)
  invoices         id, invoice_number, invoice_date, client_name, total, data (the whole invoice)
  agent_profiles   user_id, email, data (that agent's letterhead)
  settings         id (always 1), data (the settings)
"""
import time

import requests

import config


class SupabaseError(Exception):
    """Something went wrong online. .code is the database's error code when there is one
    (for example "23505" = that quote number is already used)."""

    def __init__(self, message, code=None, offline=False):
        super().__init__(message)
        self.code = code
        self.offline = offline


def _send(method, path, token=None, **kwargs):
    headers = {"apikey": config.SUPABASE_KEY, "Content-Type": "application/json"}
    headers["Authorization"] = "Bearer " + (token or config.SUPABASE_KEY)
    headers.update(kwargs.pop("headers", {}))
    try:
        r = requests.request(method, config.SUPABASE_URL + path, headers=headers,
                             timeout=config.NETWORK_TIMEOUT, **kwargs)
    except requests.RequestException:
        raise SupabaseError("No internet connection to the online database.", offline=True)
    if r.status_code >= 400:
        try:
            body = r.json()
        except ValueError:
            body = {}
        message = body.get("msg") or body.get("message") or body.get("error_description") or body.get("error") or r.text
        raise SupabaseError(str(message), code=str(body.get("code") or body.get("error_code") or r.status_code))
    return r.json() if r.content else None


# ---------------------------------------------------------------- logging in

def login_email(agent_or_email):
    """'AG01' -> 'ag01@agents.local'. A full email address is used as typed."""
    s = agent_or_email.strip()
    if "@" not in s:
        s = s.replace(" ", "") + "@" + config.AGENT_EMAIL_DOMAIN
    return s.lower()


def agent_code(email):
    """'ag01@agents.local' -> 'AG01'. Other emails are shown as they are."""
    e = (email or "").lower()
    domain = "@" + config.AGENT_EMAIL_DOMAIN
    return e[: -len(domain)].upper() if e.endswith(domain) else e


def _session_from(body):
    user = body.get("user") or {}
    return {"access_token": body["access_token"], "refresh_token": body["refresh_token"],
            "expires_at": int(body.get("expires_at") or time.time() + int(body.get("expires_in", 3600))),
            "user_id": user.get("id", ""), "email": user.get("email", "")}


def sign_in(agent_or_email, password):
    """Log in. Returns the login (tokens + user) to keep, or raises SupabaseError."""
    try:
        body = _send("POST", "/auth/v1/token?grant_type=password",
                     json={"email": login_email(agent_or_email), "password": password})
    except SupabaseError as e:
        if "invalid" in str(e).lower() and "credential" in str(e).lower():
            raise SupabaseError("Wrong agent code or password.", e.code)
        raise
    return _session_from(body)


def refreshed(login):
    """A login token lasts about an hour. This swaps an old one for a fresh one if needed."""
    if login["expires_at"] - time.time() > 60:
        return login
    body = _send("POST", "/auth/v1/token?grant_type=refresh_token", json={"refresh_token": login["refresh_token"]})
    return _session_from(body)


def change_password(login, new_password):
    _send("PUT", "/auth/v1/user", login["access_token"], json={"password": new_password})


def sign_out(login):
    try:
        _send("POST", "/auth/v1/logout", login["access_token"])
    except SupabaseError:
        pass  # logging out on this Mac works even when offline


# ---------------------------------------------------------------- tables

def select_all(token, table, order):
    """Every row of a table. Supabase gives at most 1000 rows at a time, so read in pages."""
    rows, page = [], 1000
    while True:
        part = _send("GET", f"/rest/v1/{table}", token,
                     params={"select": "*", "order": order, "limit": page, "offset": len(rows)})
        rows += part
        if len(part) < page:
            return rows


def upsert(token, table, rows, key):
    """Add rows, or replace the ones with the same key."""
    for start in range(0, len(rows), 200):
        _send("POST", f"/rest/v1/{table}", token, params={"on_conflict": key},
              headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, json=rows[start:start + 200])


def delete(token, table, column, value):
    _send("DELETE", f"/rest/v1/{table}", token, params={column: "eq." + value})


# ---------------------------------------------------------------- rows <-> app objects

def ticket_to_row(t):
    return {"code": t["code"], "name": t["name"], "supplier": t["supplier"], "adult_price": t["adultPrice"],
            "child_price": t["childPrice"], "valid_until": t["validUntil"], "confirmed_at": t.get("confirmedAt") or None}


def row_to_ticket(r):
    return {"code": r["code"], "name": r["name"], "supplier": r["supplier"], "adultPrice": float(r["adult_price"]),
            "childPrice": float(r["child_price"]), "price": float(r["adult_price"]), "validUntil": r["valid_until"],
            "confirmedAt": r.get("confirmed_at") or ""}


def item_to_row(t):
    """Transport and guide items have the same columns."""
    return {"id": t["id"], "code": t.get("code") or None, "name": t["name"], "supplier": t["supplier"], "price": t["price"]}


def row_to_item(r):
    return {"id": r["id"], "code": r.get("code") or "", "name": r["name"], "supplier": r["supplier"], "price": float(r["price"])}


def quote_to_row(q):
    return {"id": q["id"], "quote_number": q["quoteNumber"], "quote_date": q["date"],
            "client_name": q.get("clientName") or "", "total": q.get("total") or 0, "data": q}


def row_to_quote(r):
    q = dict(r["data"])
    q.update(id=r["id"], quoteNumber=r["quote_number"])
    return q


def invoice_to_row(v):
    return {"id": v["id"], "invoice_number": v["invoiceNumber"], "invoice_date": v["date"],
            "client_name": (v.get("billTo") or {}).get("name", ""), "total": v.get("total") or 0, "data": v}


def row_to_invoice(r):
    v = dict(r["data"])
    v.update(id=r["id"], invoiceNumber=r["invoice_number"])
    return v


# ---------------------------------------------------------------- whole downloads

def download_prices(token):
    return {"tickets": [row_to_ticket(r) for r in select_all(token, "tickets", "code")],
            "transport": [row_to_item(r) for r in select_all(token, "transport_items", "id")],
            "guides": [row_to_item(r) for r in select_all(token, "guide_items", "code")]}


def download_settings(token):
    rows = _send("GET", "/rest/v1/settings", token, params={"select": "data", "id": "eq.1"})
    return rows[0]["data"] if rows else None


def download_profiles(token):
    return {agent_code(r["email"]): r.get("data") or {} for r in select_all(token, "agent_profiles", "user_id")}


def save_settings(token, settings):
    upsert(token, "settings", [{"id": 1, "data": settings}], "id")


def save_my_profile(token, user_id, data):
    # The database fills in user_id and email from the login itself.
    upsert(token, "agent_profiles", [{"user_id": user_id, "data": data}], "user_id")
