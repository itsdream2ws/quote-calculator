"""Tests for the pages, the Mac database and syncing, against the pretend Supabase."""
import io
import json

import config
import store
import sync
from conftest import PASSWORD, go_offline
from helpers import today, add_days


def login(client, code="AG01"):
    r = client.post("/login", data={"agent": code, "password": PASSWORD})
    assert r.status_code == 302, r.data
    return r


def add_sample_prices(client):
    r = client.post("/settings/sample", follow_redirects=True)
    assert b"Sample price list added" in r.data


def quote_draft(client, name="Tan family"):
    """Make a quote draft through the same calls the page makes."""
    page = client.get("/quote?new=1")
    assert page.status_code == 200
    draft = {"clientName": name, "adults": 2, "children": 1, "date": today(), "serviceCharge": 50, "itemised": True,
             "group": False, "days": [{"date": add_days(today(), 7), "lines": []}], "hotels": [], "additional": []}
    for code in ("CT01", "APU"):
        r = client.post("/quote/action", json={"draft": draft, "action": {"name": "add_code", "day": 0, "code": code}}).get_json()
        assert r["kind"] == "ok", r["message"]
        draft = r["draft"]
    return draft


def test_needs_login(client):
    assert client.get("/quote").headers["Location"].endswith("/login")
    r = client.post("/login", data={"agent": "AG01", "password": "wrong"})
    assert b"Wrong agent code or password." in r.data


def test_login_save_quote_and_download(client, fake):
    login(client)
    add_sample_prices(client)
    draft = quote_draft(client)

    check = client.post("/quote/check", json={"draft": draft, "showErrors": True}).get_json()
    assert check["ok"] and check["out"]["tGrand"] == "SGD 133.00"   # 2x14 + 10 + 45 + 50 profit

    r = client.post("/quote/save", json={"draft": draft}).get_json()
    assert r["saved"] and r["number"] == f"Q-{today().replace('-', '')}-AG01-001", r
    assert "Offline" not in r["message"]
    online = fake.tables["quotes"]
    assert len(online) == 1 and online[0]["data"]["createdBy"] == "AG01" and online[0]["total"] == 133.0
    assert online[0]["data"]["tickets"][0]["travelDate"] == add_days(today(), 7)

    # saving again updates the same quote
    draft = r["draft"]
    draft["serviceCharge"] = 60
    r2 = client.post("/quote/save", json={"draft": draft}).get_json()
    assert r2["id"] == r["id"] and len(fake.tables["quotes"]) == 1 and fake.tables["quotes"][0]["total"] == 143.0

    pdf = client.get(f"/quotes/{r['id']}/file.pdf?download=1&itemised=1")
    assert pdf.data[:5] == b"%PDF-" and "attachment" in pdf.headers["Content-Disposition"]
    png = client.get(f"/quotes/{r['id']}/file.png?itemised=0")
    assert png.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"Tan family" in client.get("/quotes").data
    assert client.get(f"/quotes/{r['id']}").status_code == 200
    assert client.post("/quote/preview", json={"draft": draft}).data[:4] == b"\x89PNG"


def test_validation_stops_saving(client):
    login(client)
    r = client.post("/quote/save", json={"draft": {"clientName": "", "days": [{"date": "", "lines": []}]}}).get_json()
    assert not r["saved"] and "Enter the client name." in r["check"]["errors"]


def test_offline_save_then_sync(client, fake, monkeypatch):
    login(client)
    add_sample_prices(client)
    draft = quote_draft(client)
    real_url = config.SUPABASE_URL
    go_offline(monkeypatch)
    r = client.post("/quote/save", json={"draft": draft}).get_json()
    assert r["saved"] and "Offline" in r["message"]
    assert fake.tables["quotes"] == [] and store.unsent_count() == 1
    assert b"1 not sent yet" in client.get("/quotes").data
    page = client.post("/sync", follow_redirects=True)
    assert b"No internet" in page.data
    # the price list cannot change offline
    assert b"You are offline" in client.post("/prices/ticket", data={"code": "ZZ1", "name": "Z", "supplier": "S",
                                                                         "adultPrice": "1", "validUntil": add_days(today(), 30)},
                                                follow_redirects=True).data
    monkeypatch.setattr(config, "SUPABASE_URL", real_url)
    page = client.post("/sync", follow_redirects=True)
    assert b"Synced. Sent 1" in page.data
    assert len(fake.tables["quotes"]) == 1 and store.unsent_count() == 0


def test_two_agents_share_quotes_and_deletes(fake, tmp_path, monkeypatch):
    import app as app_module
    app_module.app.testing = True
    a, b = app_module.app.test_client(), app_module.app.test_client()

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "mac-a")
    login(a, "AG01")
    add_sample_prices(a)
    saved = a.post("/quote/save", json={"draft": quote_draft(a, "From AG01")}).get_json()

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "mac-b")   # a second Mac
    login(b, "AG02")                                               # logging in syncs
    assert b"From AG01" in b.get("/quotes").data
    assert b.get(f"/quotes/{saved['id']}/file.pdf").data[:4] == b"%PDF"
    other = b.post("/quote/save", json={"draft": quote_draft(b, "From AG02")}).get_json()
    assert "-AG02-001" in other["number"]
    b.post(f"/quotes/{saved['id']}/delete")
    assert [q["data"]["clientName"] for q in fake.tables["quotes"]] == ["From AG02"]

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "mac-a")
    a.post("/sync")
    names = [q["clientName"] for q in store.all_records("quote")]
    assert names == ["From AG02"]


def test_newer_online_copy_wins(client, fake):
    login(client)
    add_sample_prices(client)
    r = client.post("/quote/save", json={"draft": quote_draft(client)}).get_json()
    row = fake.tables["quotes"][0]
    row["data"] = {**row["data"], "clientName": "Changed elsewhere", "updatedAt": "2999-01-01T00:00:00.000Z"}
    client.post("/sync")
    assert store.get_record("quote", r["id"])["clientName"] == "Changed elsewhere"


def test_number_clash_is_renumbered(client, fake, monkeypatch):
    login(client)
    add_sample_prices(client)
    draft = quote_draft(client)
    real = config.SUPABASE_URL
    go_offline(monkeypatch)
    mine = client.post("/quote/save", json={"draft": draft}).get_json()
    # meanwhile the same number turned up online from another copy of the app
    fake.tables["quotes"].append({"id": "someone-else", "quote_number": mine["number"], "quote_date": today(),
                                  "client_name": "Other", "total": 1, "data": {"date": today(), "clientName": "Other"}})
    monkeypatch.setattr(config, "SUPABASE_URL", real)
    page = client.post("/sync", follow_redirects=True)
    assert "were changed".encode() in page.data
    numbers = sorted(q["quote_number"] for q in fake.tables["quotes"])
    assert len(set(numbers)) == 2


def test_price_list_pages(client, fake):
    login(client)
    r = client.post("/prices/ticket", data={"code": "x 1", "name": "Thing", "supplier": "Sup", "adultPrice": "10",
                                            "childPrice": "", "validUntil": add_days(today(), 30)}, follow_redirects=True)
    assert b"Added X1." in r.data
    t = fake.tables["tickets"][0]
    assert t["code"] == "X1" and t["child_price"] == 10 and t["confirmed_at"] == today()
    # the same code can't be used twice, even by a transfer
    r = client.post("/prices/transport", data={"code": "X1", "name": "Car", "supplier": "Sup", "price": "5"}, follow_redirects=True)
    assert b"already used by a ticket" in r.data
    client.post("/prices/transport", data={"code": "CAR", "name": "Car", "supplier": "Sup", "price": "5"})
    client.post("/prices/guide", data={"code": "G1", "name": "Zoo", "supplier": "Guides", "price": "100"})
    page = client.get("/prices").data
    assert b"CAR" in page and b"Zoo" in page and b"X1" in page
    # editing a ticket's code moves it
    client.post("/prices/ticket", data={"editing": "X1", "code": "X2", "name": "Thing", "supplier": "Sup", "adultPrice": "12",
                                        "validUntil": add_days(today(), 30)})
    assert [r["code"] for r in fake.tables["tickets"]] == ["X2"]
    client.post("/prices/ticket/X2/delete")
    assert fake.tables["tickets"] == []
    gid = fake.tables["guide_items"][0]["id"]
    client.post(f"/prices/guide/{gid}/delete")
    assert fake.tables["guide_items"] == []


def test_invoice_flow_with_logo(client, fake):
    login(client)
    page = client.get("/invoice?new=1")
    assert page.status_code == 200
    from PIL import Image
    pic = io.BytesIO()
    Image.new("RGB", (1200, 400), (10, 120, 130)).save(pic, "PNG")
    r = client.post("/invoice/logo", data={"logo": (io.BytesIO(pic.getvalue()), "logo.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"Logo saved" in r.data
    prof = fake.tables["agent_profiles"][0]
    assert prof["email"] == "ag01@agents.local" and prof["data"]["logo"].startswith("data:image/png;base64,")

    draft = {"invoiceNumber": f"PI-{today().replace('-', '')}-AG01-001", "autoNumber": True, "title": "PROFORMA INVOICE",
             "date": today(), "companyName": "Horeb", "clientName": "ACME", "currency": "SGD", "taxRate": 9,
             "items": [{"description": "Package", "qty": 2, "unitPrice": 450}], "itemised": True}
    act = client.post("/invoice/action", json={"draft": draft, "action": {"name": "add_item"}}).get_json()
    assert len(act["draft"]["items"]) == 2 and act["focus"] == "items.1.description"
    bad = client.post("/invoice/save", json={"draft": act["draft"]}).get_json()
    assert not bad["saved"] and "Line 2: write a description." in bad["check"]["errors"]
    ok = client.post("/invoice/save", json={"draft": draft}).get_json()
    assert ok["saved"] and fake.tables["invoices"][0]["total"] == 981.0
    assert client.get(f"/invoices/{ok['id']}/file.pdf").data[:4] == b"%PDF"
    assert b"ACME" in client.get("/invoice").data
    lh = client.post("/invoice/letterhead", json={"draft": {**draft, "payment": "DBS 123"}}).get_json()
    assert lh["ok"] and fake.tables["agent_profiles"][0]["data"]["payment"] == "DBS 123"


def test_report_page_and_csv(client):
    login(client)
    add_sample_prices(client)
    client.post("/quote/save", json={"draft": quote_draft(client)})
    month = add_days(today(), 7)[:7]
    page = client.get(f"/report?month={month}")
    assert b"City Tours Co" in page.data and b"Metro Transport" in page.data
    csv = client.get(f"/report.csv?from={month}-01&to={month}-28&supplier=Metro+Transport")
    text = csv.data.decode("utf-8-sig")
    assert "Metro Transport,Transport" in text and "City Tours" not in text


def test_settings_password_and_backup(client, fake):
    login(client)
    r = client.post("/settings", data={"businessName": "Horeb Tours", "currency": "SGD", "defaultServiceCharge": "80",
                                       "profitDisplay": "profit", "footer": "Thanks"}, follow_redirects=True)
    assert b"Settings saved." in r.data and fake.tables["settings"][0]["data"]["businessName"] == "Horeb Tours"
    assert b"Horeb Tours" in client.get("/quote").data
    r = client.post("/settings/password", data={"new": "new-password-9", "again": "new-password-9"}, follow_redirects=True)
    assert b"Password changed" in r.data
    backup = json.loads(client.get("/backup.json").data)
    backup["quotes"] = [{"id": "old1", "quoteNumber": "Q-20250101-001", "date": "2025-01-01", "clientName": "Restored",
                         "updatedAt": "2025-01-01T00:00:00.000Z"}]
    r = client.post("/restore", data={"file": (io.BytesIO(json.dumps(backup).encode()), "b.json")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"Added 1" in r.data and store.unsent_count() == 1


def test_logout_waits_for_unsent(client, monkeypatch):
    login(client)
    add_sample_prices(client)
    draft = quote_draft(client)
    go_offline(monkeypatch)
    client.post("/quote/save", json={"draft": draft})
    r = client.post("/logout", follow_redirects=True)
    assert b"not sent to Supabase yet" in r.data and sync.current_login()


def test_other_websites_are_blocked(fake):
    import app as app_module
    app_module.app.testing = False
    try:
        c = app_module.app.test_client()
        r = c.post("/sync", headers={"Origin": "https://evil.example", "Host": f"127.0.0.1:{config.PORT}"})
        assert r.status_code == 403
        r = c.get("/login", headers={"Host": "evil.example"})
        assert r.status_code == 403
    finally:
        app_module.app.testing = True
