"""Keeping this Mac and Supabase in step.

sync_now() does, in this order:
  1. gets a fresh login token (Supabase tokens last about an hour)
  2. quotes and invoices: downloads everyone's, merges them with the ones on this Mac,
     then sends up the ones changed here (and the deletes made here)
  3. sends your own letterhead (logo etc.) if you changed it, then downloads everyone's
  4. downloads the price list and the settings

How two copies of the same quote are merged: the one saved most recently wins
(every quote has an updatedAt time).

Price list and settings changes are not queued for later: the page sends them to Supabase
straight away (so you need internet for those), and then refreshes the copy here.
"""
import store
import supabase_api as api
from helpers import now_iso
import quotes as quote_rules
import invoices as invoice_rules

TABLES = {  # kind -> (table, number column, row maker, row reader, number field)
    "quote": ("quotes", "quote_number", api.quote_to_row, api.row_to_quote, "quoteNumber"),
    "invoice": ("invoices", "invoice_number", api.invoice_to_row, api.row_to_invoice, "invoiceNumber"),
}


def current_login():
    """The login saved on this Mac, or None if nobody has logged in yet."""
    return store.get("login")


def fresh_token():
    """A login token that works right now (refreshing it if needed). Raises SupabaseError."""
    login = current_login()
    if not login:
        raise api.SupabaseError("Log in first.")
    new = api.refreshed(login)
    if new is not login:
        new["agent"] = login.get("agent") or api.agent_code(new["email"])
        store.put("login", new)
    return new["access_token"]


def sync_now():
    """Do a full sync. Returns a short summary. Raises SupabaseError if offline."""
    token = fresh_token()
    login = current_login()
    summary = {"sent": 0, "received": 0, "renumbered": []}
    for kind in ("quote", "invoice"):
        _sync_records(token, kind, login.get("agent", ""), summary)

    if store.get("my_profile_dirty"):
        mine = (store.get("profiles") or {}).get(login.get("agent"), {})
        api.save_my_profile(token, login["user_id"], mine)
        store.put("my_profile_dirty", False)
    store.put("profiles", api.download_profiles(token))

    store.put("prices", api.download_prices(token))
    settings = api.download_settings(token)
    if settings is not None:
        store.put("settings", settings)
    store.put("last_sync", now_iso())
    return summary


def _sync_records(token, kind, agent, summary):
    table, number_col, to_row, from_row, number_field = TABLES[kind]

    # 1. Download everyone's and merge.
    online = {r["id"]: from_row(r) for r in api.select_all(token, table, "id")}
    unsent = {rec["id"]: (rec, deleted) for rec, deleted in store.unsent(kind)}
    local_ids = {r["id"] for r in store.all_records(kind)}
    for rid, rec in online.items():
        mine = unsent.get(rid)
        if mine and (mine[1] or str(mine[0].get("updatedAt", "")) >= str(rec.get("updatedAt", ""))):
            continue  # the copy here is newer (or was deleted here): it gets sent below
        if mine:
            del unsent[rid]  # someone saved a newer copy online: take theirs
        if rid not in local_ids:
            summary["received"] += 1
        store.save_record(kind, rec, dirty=False)
    # Quotes that were sent before but are no longer online were deleted by someone else.
    for rid in local_ids - set(online) - set(unsent):
        store.forget_record(kind, rid)

    # 2. Send what changed here.
    for rid, (rec, deleted) in unsent.items():
        if deleted:
            if rid in online:
                api.delete(token, table, "id", rid)
            store.forget_record(kind, rid)
            continue
        try:
            api.upsert(token, table, [to_row(rec)], "id")
        except api.SupabaseError as e:
            if e.code != "23505":  # 23505 = that number is already used by another quote
                raise
            old = rec[number_field]
            everyone = list(online.values()) + store.all_records(kind)
            if kind == "quote":
                rec[number_field] = quote_rules.next_quote_number(everyone, rec["date"], agent)
            else:
                rec[number_field] = invoice_rules.next_invoice_number(everyone, rec["date"], agent)
            api.upsert(token, table, [to_row(rec)], "id")
            summary["renumbered"].append(f"{old} → {rec[number_field]}")
        store.save_record(kind, rec, dirty=False)
        summary["sent"] += 1
