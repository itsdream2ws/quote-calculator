"""Settings for the app. Change these if the database or the time zone ever changes."""
import os
from pathlib import Path

# The online database (Supabase). The publishable key is meant to be public: it only lets
# the app ask Supabase to log someone in. Row level security in the database blocks every
# read and write until an agent has logged in (see ../supabase/schema.sql).
SUPABASE_URL = "https://lhbxixvazowgiquiexzt.supabase.co"
SUPABASE_KEY = "sb_publishable_7b556YBCnP2oRi7NDO8cGg_WNlPYX_t"

# Agents log in with a code like AG01. Behind the scenes that is the login email
# ag01@agents.local (the address does not need to exist).
AGENT_EMAIL_DOMAIN = "agents.local"

# "Today" on quotes and price checks uses this time zone.
TIMEZONE = "Asia/Singapore"

# Where the app keeps its data on this Mac (the local database file).
# On a Mac that is ~/Library/Application Support/Quote Calculator/
# You can point it somewhere else by setting QC_DATA_DIR before starting the app.
_default_dir = Path.home() / "Library" / "Application Support" / "Quote Calculator"
DATA_DIR = Path(os.environ.get("QC_DATA_DIR", _default_dir))

# The app runs on this address on your own computer only (nobody else can reach it).
HOST = "127.0.0.1"
PORT = int(os.environ.get("QC_PORT", "5055"))

# How long to wait for Supabase before giving up and working offline (seconds).
NETWORK_TIMEOUT = 15
