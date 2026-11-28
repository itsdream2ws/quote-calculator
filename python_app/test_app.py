"""Automatic checks. Run them with:   .venv/bin/python3 -m pytest test_app.py

They use a pretend Supabase (FakeSupabase below) and a temporary folder for the database on
this Mac, so they never touch your real data.
"""
import json

import pytest

import data
import pdf
import rules

PASSWORD = "secret"


# =============================================================== a pretend Supabase

class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self.content = json.dumps(body).encode() if body is not None else b""
        self.text = self.content.decode()

    def json(self):
        return json.loads(self.content)


class FakeSupabase:
    """Answers the same web addresses as Supabase and keeps the tables in memory."""
    KEYS = {"tickets": "code", "transport_items": "id", "guide_items": "id", "quotes": "id", "settings": "id"}

    def __init__(self):
        self.tables = {name: [] for name in self.KEYS}
        self.tables["settings"] = [{"id": 1, "data": {"businessName": "Horeb Tours", "currency": "SGD",
                                                      "defaultServiceCharge": 50, "profitDisplay": "service"}}]
        self.online = True

    def __call__(self, method, url, headers=None, params=None, json=None, timeout=None):
        if not self.online:
            raise data.requests.ConnectionError("no internet")
        path = url[len(data.SUPABASE_URL):]
        params = params or {}
        if path.startswith("/auth/v1/token"):
            if json.get("password") == PASSWORD or json.get("refresh_token") == "refresh":
                return FakeResponse(200, {"access_token": "token", "refresh_token": "refresh", "expires_in": 3600})
            return FakeResponse(400, {"error_description": "Invalid login credentials"})
        if headers["Authorization"] != "Bearer token":
            return FakeResponse(401, {"message": "not logged in"})
        table = path.split("/")[-1]
        rows = self.tables[table]
        if method == "GET":
            out = [r for r in rows if all(str(r.get(k)) == v[3:] for k, v in params.items() if str(v).startswith("eq."))]
            off, limit = params.get("offset", 0), params.get("limit", 1000)
            return FakeResponse(200, out[off:off + limit])
        if method == "DELETE":
            (column, value), = params.items()
            self.tables[table] = [r for r in rows if str(r.get(column)) != value[3:]]
            return FakeResponse(204)
        key = params["on_conflict"]
        for new in json:
            if table == "quotes" and any(r["quote_number"] == new["quote_number"] and r["id"] != new["id"] for r in rows):
                return FakeResponse(409, {"code": "23505", "message": "duplicate key"})
            old = next((r for r in rows if r[key] == new[key]), None)
            old.update(new) if old else rows.append(dict(new))
        return FakeResponse(201)


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    server = FakeSupabase()
    monkeypatch.setattr(data.requests, "request", server)
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    return server


def logged_in_with_prices(fake):
    data.log_in("ag01", PASSWORD)
    valid = rules.add_days(rules.today(), 60)
    data.save_price_item("ticket", {"code": "CT01", "name": "City tour", "supplier": "City Tours Co", "adultPrice": 14,
                                    "childPrice": 10, "price": 14, "validUntil": valid, "confirmedAt": rules.today()})
    data.save_price_item("transport", {"id": "t1", "code": "APU", "name": "Airport pickup", "supplier": "Metro", "price": 45})


def a_draft(prices):
    """2 adults + 1 child: City tour, airport pickup, lunch, a hotel and 100 profit."""
    d = rules.blank_draft({"defaultServiceCharge": 100})
    d.update(clientName="Tan family", adults=2, children=1)
    d["days"][0]["date"] = rules.add_days(rules.today(), 5)
    for code in ("CT01", "APU"):
        kind, item = rules.find_code(prices, code)
        d["days"][0]["lines"].append(rules.line_from_price_list(item, kind, d))
    d["days"][0]["lines"].append({"type": "meal", "meal": "Lunch", "description": "", "supplier": "Kopitiam",
                                  "adults": "2", "children": "1", "adultPrice": "10", "childPrice": "5"})
    d["hotels"].append({"description": "Grand Central", "supplier": "", "amount": "500"})
    return d


def save(d, agent="AG01"):
    """Save like the Save button does (without the screen)."""
    q = rules.build_quote(d, data.settings())
    q.update(id=rules.new_id(), quoteNumber=rules.next_quote_number(data.all_quotes(), d["date"], agent),
             createdBy=agent, updatedAt=rules.now_iso())
    data.keep_quote(q)
    return q


# =============================================================== the rules

def test_rounding_and_numbers():
    assert rules.round2(2.345) == 2.35          # halves go up, unlike Python's round()
    assert rules.round2(1.005) == 1.01
    assert rules.fmt(1234.5) == "1,234.50"
    assert rules.whole("2") == 2 and rules.whole("2.5") is None and rules.whole("") is None


def test_totals_and_checks(fake):
    logged_in_with_prices(fake)
    d = a_draft(data.prices())
    t = rules.totals(d)
    # city tour 2 x 14 + 1 x 10 = 38, pickup 45, lunch 2 x 10 + 5 = 25, hotel 500, profit 100
    assert (t["tickets"], t["transport"], t["meals"], t["hotel"], t["total"]) == (38, 45, 25, 500, 708)
    assert rules.check_quote(d, data.prices()) == ([], [])

    d["days"][0]["lines"][0]["adultPrice"] = "15"   # a price changed on the quote is only a warning
    errors, warnings = rules.check_quote(d, data.prices())
    assert errors == [] and "price list says 14.00" in warnings[0]

    d["clientName"] = " "
    d["days"][0]["lines"][1]["qty"] = "0"
    errors, _ = rules.check_quote(d, data.prices())
    assert errors == ["Enter the client name.", "Day 1, APU: quantity must be a whole number, 1 or more."]


def test_expired_ticket_is_an_error(fake):
    logged_in_with_prices(fake)
    d = a_draft(data.prices())
    prices = data.prices()
    prices["tickets"][0]["validUntil"] = rules.add_days(rules.today(), -1)
    errors, _ = rules.check_quote(d, prices)
    assert any("expired" in e for e in errors)


def test_price_list_codes_are_unique(fake):
    logged_in_with_prices(fake)
    item, error = rules.check_price_item(data.prices(), "guide", {"code": "ct01", "name": "x", "supplier": "y", "price": "1"})
    assert item is None and error == "Code CT01 is already used by a ticket (City tour)."
    editing = data.prices()["tickets"][0]          # changing the ticket itself keeps its code
    form = {"code": "CT01", "name": "City tour", "supplier": "City Tours Co", "adultPrice": "16", "childPrice": "",
            "validUntil": editing["validUntil"]}
    item, error = rules.check_price_item(data.prices(), "ticket", form, editing)
    assert error is None and item["childPrice"] == 16


def test_saved_quote_has_the_websites_shape(fake):
    logged_in_with_prices(fake)
    q = rules.build_quote(a_draft(data.prices()), data.settings())
    assert q["tickets"][0] == {"code": "CT01", "name": "City tour", "supplier": "City Tours Co", "adults": 2, "children": 1,
                               "adultPrice": 14.0, "childPrice": 10.0, "total": 38.0, "travelDate": q["days"][0]["date"],
                               "pax": 3, "unitPrice": 12.67}
    assert q["transport"][0]["date"] == q["transport"][0]["travelDate"]
    assert q["meals"][0]["pax"] == 3 and q["subtotalHotel"] == 500 and q["total"] == 708


def test_quote_numbers_include_the_agent():
    quotes = [{"quoteNumber": "Q-20261128-AG01-001"}, {"quoteNumber": "Q-20261128-AG01-007"}, {"quoteNumber": "Q-20261128-002"}]
    assert rules.next_quote_number(quotes, "2026-11-28", "AG01") == "Q-20261128-AG01-008"
    assert rules.next_quote_number(quotes, "2026-11-28", "AG02") == "Q-20261128-AG02-001"


def test_supplier_report(fake, tmp_path):
    logged_in_with_prices(fake)
    q = save(a_draft(data.prices()))
    first, last = rules.month_range(q["days"][0]["date"])
    lines = rules.report_lines(data.all_quotes(), first, last)
    sums = rules.report_by_supplier(lines)
    assert sums == {"City Tours Co": 3800, "Kopitiam": 2500, "Metro": 4500, "(No supplier set)": 50000}
    rules.write_csv(lines, tmp_path / "report.csv")
    assert "City Tours Co,Ticket" in (tmp_path / "report.csv").read_text(encoding="utf-8-sig")


# =============================================================== saving and sync

def test_offline_quotes_are_sent_at_the_next_sync(fake):
    logged_in_with_prices(fake)
    fake.online = False
    q = save(a_draft(data.prices()))
    with pytest.raises(data.OnlineError):
        data.sync_now()
    assert data.unsent_ids() == {q["id"]}        # still safe on this Mac

    fake.online = True
    assert data.sync_now().startswith("Synced: 1 sent")
    assert data.unsent_ids() == set() and fake.tables["quotes"][0]["quote_number"] == q["quoteNumber"]
    assert data.settings()["businessName"] == "Horeb Tours"


def test_two_agents_share_quotes_and_deletes(fake):
    logged_in_with_prices(fake)
    q = save(a_draft(data.prices()))
    data.sync_now()
    data.forget_quote(q["id"])                   # pretend this is a second Mac that hasn't got it yet
    assert "1 new from other agents" in data.sync_now()
    data.delete_quote(q["id"])
    data.sync_now()
    assert fake.tables["quotes"] == [] and data.all_quotes() == []


def test_newer_copy_wins(fake):
    logged_in_with_prices(fake)
    q = save(a_draft(data.prices()))
    data.sync_now()
    fake.tables["quotes"][0]["data"] = dict(q, clientName="Changed online", updatedAt="2999-01-01T00:00:00.000Z")
    data.keep_quote(dict(q, clientName="Changed here"))   # older than the online change
    data.sync_now()
    assert data.all_quotes()[0]["clientName"] == "Changed online"


def test_taken_number_is_renumbered(fake):
    logged_in_with_prices(fake)
    q = save(a_draft(data.prices()))
    fake.tables["quotes"].append({"id": "other", "quote_number": q["quoteNumber"], "data": {}})
    assert "Renumbered" in data.sync_now()
    assert data.all_quotes()[0]["quoteNumber"].endswith("-002")


def test_ticket_code_change_replaces_the_row(fake):
    logged_in_with_prices(fake)
    t = dict(data.prices()["tickets"][0], code="CT02")
    data.save_price_item("ticket", t, old_key="CT01")
    assert [r["code"] for r in fake.tables["tickets"]] == ["CT02"]


def test_wrong_password(fake):
    with pytest.raises(data.OnlineError, match="Wrong agent code or password"):
        data.log_in("AG01", "nope")


# =============================================================== the PDF

def test_pdf(fake, tmp_path):
    logged_in_with_prices(fake)
    q = save(a_draft(data.prices()))
    q["clientName"] = "Tan 陈 family — VIP"   # letters Helvetica can't show become "?"
    for itemised in (True, False):
        q["itemised"] = itemised
        path = tmp_path / pdf.file_name(q)
        pdf.quote_pdf(q, data.settings(), path)
        assert path.read_bytes()[:4] == b"%PDF"
