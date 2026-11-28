"""Saving: the database on this Mac (SQLite), and the online database (Supabase).

On this Mac (works without internet), one file: ~/Library/Application Support/Quote Calculator/quote-calculator.db
  quotes   one row per quote: id, data (the whole quote as JSON text),
           dirty = 1 when it changed here and isn't sent to Supabase yet,
           deleted = 1 when it was deleted here and the delete isn't sent yet
  kv       everything else, as name -> JSON text: "login", "prices", "settings", "last_sync"

Online (Supabase, shared with the website). Supabase is used over plain web requests:
  /auth/v1/token        log in, and swap an old login token for a fresh one
  /rest/v1/<table>      read and write a table
Every request carries the agent's login token, so the database's own rules (row level security)
decide what is allowed, exactly like the website.

Sync (sync_now): download everyone's quotes and keep the newer copy of each, send the quotes
changed here and the deletes made here, then download the price list and the settings.
The price list is never changed offline: those changes go straight to Supabase.
"""
import json
import os
import sqlite3
import time
from pathlib import Path

import requests

import rules

# ---------------------------------------------------------------- settings you might change

SUPABASE_URL = "https://lhbxixvazowgiquiexzt.supabase.co"
# The publishable key is meant to be public: it only lets the app ask Supabase to log someone in.
SUPABASE_KEY = "sb_publishable_7b556YBCnP2oRi7NDO8cGg_WNlPYX_t"
AGENT_EMAIL_DOMAIN = "agents.local"     # agent AG01 logs in as ag01@agents.local
NETWORK_TIMEOUT = 10                    # seconds to wait for Supabase before saying "no internet"
DATA_DIR = Path(os.environ.get("QC_DATA_DIR", Path.home() / "Library" / "Application Support" / "Quote Calculator"))

# the price list tables: kind -> (Supabase table, key column, key field in the app)
PRICE_TABLES = {"ticket": ("tickets", "code", "code"), "transport": ("transport_items", "id", "id"),
                "guide": ("guide_items", "id", "id")}


class OnlineError(Exception):
    """Something went wrong talking to Supabase. .code is the database's error code, if any
    (for example "23505" means "that quote number is already used")."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# =============================================================== this Mac

def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_DIR / "quote-calculator.db")
    con.executescript("""
        create table if not exists quotes (id text primary key, data text not null,
                                           dirty integer not null default 0, deleted integer not null default 0);
        create table if not exists kv (key text primary key, value text not null);""")
    return con


def get(key, default=None):
    with db() as con:
        row = con.execute("select value from kv where key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(key, value):
    with db() as con:
        con.execute("insert or replace into kv (key, value) values (?, ?)", (key, json.dumps(value)))


def prices():
    return get("prices", {"tickets": [], "transport": [], "guides": []})


def settings():
    return get("settings", {"currency": "SGD", "defaultServiceCharge": 0, "profitDisplay": "service"})


def all_quotes():
    """Every quote on this Mac (not counting deleted ones), newest first."""
    with db() as con:
        rows = con.execute("select data from quotes where deleted = 0").fetchall()
    quotes = [json.loads(r[0]) for r in rows]
    return sorted(quotes, key=lambda q: (q.get("date", ""), q.get("quoteNumber", "")), reverse=True)


def unsent_ids():
    with db() as con:
        return {r[0] for r in con.execute("select id from quotes where dirty = 1")}


def keep_quote(q, dirty=True):
    """Save a quote on this Mac. dirty=True means it still has to be sent to Supabase."""
    with db() as con:
        con.execute("insert or replace into quotes (id, data, dirty, deleted) values (?, ?, ?, 0)",
                    (q["id"], json.dumps(q), int(dirty)))


def delete_quote(quote_id):
    """Hide it now. The delete is sent to Supabase at the next sync."""
    with db() as con:
        con.execute("update quotes set deleted = 1, dirty = 1 where id = ?", (quote_id,))


def forget_quote(quote_id):
    with db() as con:
        con.execute("delete from quotes where id = ?", (quote_id,))


# =============================================================== Supabase

def send(method, path, token=None, **kwargs):
    """One web request to Supabase. Returns the answer (JSON) or raises OnlineError."""
    headers = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + (token or SUPABASE_KEY),
               "Content-Type": "application/json", **kwargs.pop("headers", {})}
    try:
        r = requests.request(method, SUPABASE_URL + path, headers=headers, timeout=NETWORK_TIMEOUT, **kwargs)
    except requests.RequestException:
        raise OnlineError("No internet connection. Your quotes are safe on this Mac: sync again later.")
    if r.status_code >= 400:
        try:
            body = r.json()
        except ValueError:
            body = {}
        message = body.get("msg") or body.get("message") or body.get("error_description") or r.text
        raise OnlineError(str(message), str(body.get("code") or body.get("error_code") or r.status_code))
    return r.json() if r.content else None


def _keep_login(body, agent):
    put("login", {"agent": agent, "access_token": body["access_token"], "refresh_token": body["refresh_token"],
                  "expires_at": time.time() + int(body.get("expires_in", 3600))})


def log_in(agent, password):
    """Log in with an agent code like AG01. Needs internet. Raises OnlineError."""
    agent = agent.strip().upper().replace(" ", "")
    try:
        body = send("POST", "/auth/v1/token?grant_type=password",
                    json={"email": agent.lower() + "@" + AGENT_EMAIL_DOMAIN, "password": password})
    except OnlineError as e:
        if "invalid" in str(e).lower():
            raise OnlineError("Wrong agent code or password.")
        raise
    _keep_login(body, agent)


def agent():
    """The agent code logged in on this Mac, or None."""
    return (get("login") or {}).get("agent")


def token():
    """A login token that works now. Supabase tokens last an hour, so an old one is swapped
    for a fresh one with the refresh token (which needs internet)."""
    login = get("login")
    if not login:
        raise OnlineError("Log in first.")
    if login["expires_at"] - time.time() < 60:
        try:
            body = send("POST", "/auth/v1/token?grant_type=refresh_token", json={"refresh_token": login["refresh_token"]})
        except OnlineError as e:
            if e.code and e.code[0] == "4":   # 400/401: the login really has expired
                raise OnlineError("Your login has expired. Log out and log in again.")
            raise
        _keep_login(body, login["agent"])
        return body["access_token"]
    return login["access_token"]


def select_all(table, order):
    """Every row of a table. Supabase gives at most 1000 rows at a time, so ask page by page."""
    rows = []
    while True:
        part = send("GET", f"/rest/v1/{table}", token(),
                    params={"select": "*", "order": order, "limit": 1000, "offset": len(rows)})
        rows += part
        if len(part) < 1000:
            return rows


def upsert(table, row, key):
    """Add a row, or replace the row with the same key."""
    send("POST", f"/rest/v1/{table}", token(), params={"on_conflict": key},
         headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, json=[row])


def delete_row(table, column, value):
    send("DELETE", f"/rest/v1/{table}", token(), params={column: "eq." + value})


# ---------------------------------------------------------------- the price list (online only)

def download_prices():
    tickets = [{"code": r["code"], "name": r["name"], "supplier": r["supplier"], "adultPrice": float(r["adult_price"]),
                "childPrice": float(r["child_price"]), "price": float(r["adult_price"]), "validUntil": r["valid_until"],
                "confirmedAt": r.get("confirmed_at") or ""} for r in select_all("tickets", "code")]

    def items(table):
        return [{"id": r["id"], "code": r.get("code") or "", "name": r["name"], "supplier": r["supplier"],
                 "price": float(r["price"])} for r in select_all(table, "code")]
    put("prices", {"tickets": tickets, "transport": items("transport_items"), "guides": items("guide_items")})


def save_price_item(kind, item, old_key=None, refresh=True):
    """Save a ticket / transfer / guide to Supabase, then refresh the copy on this Mac.
    old_key: the code of a ticket being edited (a ticket's code is its key, so a new code
    means the old row has to go). refresh=False skips downloading the price list again."""
    table, key_col, key_field = PRICE_TABLES[kind]
    if kind == "ticket":
        row = {"code": item["code"], "name": item["name"], "supplier": item["supplier"], "adult_price": item["adultPrice"],
               "child_price": item["childPrice"], "valid_until": item["validUntil"], "confirmed_at": item["confirmedAt"]}
    else:
        row = {"id": item["id"], "code": item["code"], "name": item["name"], "supplier": item["supplier"], "price": item["price"]}
    upsert(table, row, key_col)
    if old_key and old_key != item[key_field]:
        delete_row(table, key_col, old_key)
    if refresh:
        download_prices()


def delete_price_item(kind, item):
    table, key_col, key_field = PRICE_TABLES[kind]
    delete_row(table, key_col, item[key_field])
    download_prices()


# ---------------------------------------------------------------- quotes and sync

def quote_row(q):
    return {"id": q["id"], "quote_number": q["quoteNumber"], "quote_date": q["date"],
            "client_name": q.get("clientName") or "", "total": q.get("total") or 0, "data": q}


def send_quote(q, everyone=()):
    """Send one quote to Supabase. If its number was taken meanwhile (by an agent online),
    it gets the next free number. Returns the old number if it was renumbered, else None."""
    try:
        upsert("quotes", quote_row(q), "id")
        renumbered = None
    except OnlineError as e:
        if e.code != "23505":          # 23505 = that quote number is already used
            raise
        renumbered = q["quoteNumber"]
        q["quoteNumber"] = rules.next_quote_number(list(everyone) + all_quotes(), q["date"], agent())
        upsert("quotes", quote_row(q), "id")
    keep_quote(q, dirty=False)
    return renumbered


def sync_now():
    """Full sync. Returns a short summary for the screen. Raises OnlineError when offline."""
    with db() as con:
        unsent = {r[0]: (json.loads(r[1]), bool(r[2]))
                  for r in con.execute("select id, data, deleted from quotes where dirty = 1")}
        on_this_mac = {r[0] for r in con.execute("select id from quotes")}

    # 1. Download everyone's quotes. For a quote changed both here and online, the newer copy wins.
    online = {}
    for r in select_all("quotes", "id"):
        q = dict(r["data"], id=r["id"], quoteNumber=r["quote_number"])
        online[q["id"]] = q
    received = 0
    for qid, q in online.items():
        mine = unsent.get(qid)
        if mine and (mine[1] or mine[0].get("updatedAt", "") >= q.get("updatedAt", "")):
            continue                   # the copy here is newer, or was deleted here: it's sent below
        unsent.pop(qid, None)
        received += qid not in on_this_mac
        keep_quote(q, dirty=False)
    for qid in on_this_mac - set(online) - set(unsent):
        forget_quote(qid)              # it was sent before and someone deleted it online

    # 2. Send what changed here.
    sent, renumbered = 0, []
    for qid, (q, deleted) in unsent.items():
        if deleted:
            if qid in online:
                delete_row("quotes", "id", qid)
            forget_quote(qid)
        else:
            old = send_quote(q, online.values())
            if old:
                renumbered.append(f"{old} is now {q['quoteNumber']}")
        sent += 1

    # 3. Download the price list and settings.
    download_prices()
    rows = send("GET", "/rest/v1/settings", token(), params={"select": "data", "id": "eq.1"})
    if rows:
        put("settings", rows[0]["data"])
    put("last_sync", rules.now_iso())
    summary = f"Synced: {sent} sent, {received} new from other agents."
    return summary + (" Renumbered: " + ", ".join(renumbered) + "." if renumbered else "")
