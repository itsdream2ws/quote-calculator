"""The database on this Mac (one SQLite file), so the app works without internet.

Tables:
  records   one row per saved quote or invoice:
              kind     "quote" or "invoice"
              id       the quote's / invoice's id
              data     the whole quote or invoice as JSON text
              dirty    1 = changed here and not sent to Supabase yet
              deleted  1 = deleted here; the delete is sent to Supabase at the next sync
  kv        everything else, as key -> JSON text:
              "prices"      the price list (a copy of Supabase's, refreshed at each sync)
              "settings"    business name, currency, default profit... (copy of Supabase's)
              "profiles"    every agent's letterhead, by agent code (copy of Supabase's)
              "my_profile_dirty"  true when your own letterhead still has to be sent
              "login"       who is logged in, and the tokens Supabase gave us
              "last_sync"   when the last successful sync finished

SQLite comes with Python, so there is nothing to install. The file is at
config.DATA_DIR / "quote-calculator.db".
"""
import json
import sqlite3

import config

SCHEMA = """
create table if not exists records (
  kind    text not null,
  id      text not null,
  data    text not null,
  dirty   integer not null default 0,
  deleted integer not null default 0,
  primary key (kind, id)
);
create table if not exists kv (
  key   text primary key,
  value text not null
);
"""


def db_path():
    return config.DATA_DIR / "quote-calculator.db"


def connect():
    """Open the database (creating the folder and tables the first time)."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


# ---------------------------------------------------------------- key -> value

def get(key, default=None):
    with connect() as con:
        row = con.execute("select value from kv where key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def put(key, value):
    with connect() as con:
        con.execute("insert into kv (key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
                    (key, json.dumps(value)))


def remove(key):
    with connect() as con:
        con.execute("delete from kv where key = ?", (key,))


# ---------------------------------------------------------------- quotes and invoices

def all_records(kind):
    """Every saved quote (kind="quote") or invoice (kind="invoice"), not counting deleted ones."""
    with connect() as con:
        rows = con.execute("select data from records where kind = ? and deleted = 0", (kind,)).fetchall()
    return [json.loads(r["data"]) for r in rows]


def get_record(kind, record_id):
    with connect() as con:
        row = con.execute("select data from records where kind = ? and id = ? and deleted = 0",
                          (kind, record_id)).fetchone()
    return json.loads(row["data"]) if row else None


def save_record(kind, record, dirty=True):
    """Save a quote or invoice here. dirty=True means it still has to be sent to Supabase."""
    with connect() as con:
        con.execute("""insert into records (kind, id, data, dirty, deleted) values (?, ?, ?, ?, 0)
                       on conflict(kind, id) do update set data = excluded.data, dirty = excluded.dirty, deleted = 0""",
                    (kind, record["id"], json.dumps(record), 1 if dirty else 0))


def delete_record(kind, record_id):
    """Hide it now; the next sync deletes it from Supabase too."""
    with connect() as con:
        con.execute("update records set deleted = 1, dirty = 1 where kind = ? and id = ?", (kind, record_id))


def forget_record(kind, record_id):
    """Remove it from this Mac completely (after Supabase has deleted it too)."""
    with connect() as con:
        con.execute("delete from records where kind = ? and id = ?", (kind, record_id))


def unsent(kind):
    """Quotes / invoices changed here and not sent yet: list of (record, deleted)."""
    with connect() as con:
        rows = con.execute("select data, deleted from records where kind = ? and dirty = 1", (kind,)).fetchall()
    return [(json.loads(r["data"]), bool(r["deleted"])) for r in rows]


def is_unsent(kind, record_id):
    with connect() as con:
        row = con.execute("select dirty from records where kind = ? and id = ?", (kind, record_id)).fetchone()
    return bool(row and row["dirty"])


def unsent_count():
    with connect() as con:
        return con.execute("select count(*) from records where dirty = 1").fetchone()[0]
