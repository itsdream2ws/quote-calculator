"""Tests for the rules (no web pages, no internet). Run all tests with:  python3 -m pytest tests"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import invoices
import prices
import quotes
import report
from helpers import round2, today, add_days, pax_label, month_range

SETTINGS = {"currency": "SGD", "defaultServiceCharge": 50}
REPO = Path(__file__).resolve().parents[2]


def sample_prices():
    p = prices.sample_price_list(prices.empty_price_list())
    return p


def test_round2_rounds_halves_up():
    assert round2(2.345) == 2.35
    assert round2(0.125) == 0.13
    assert round2("10") == 10.0
    assert round2("abc") == 0.0


def test_helpers():
    assert pax_label(7, 1) == "7 A+1C"
    assert pax_label(2, 0) == "2 A"
    assert month_range(2028, 2) == ("2028-02-01", "2028-02-29")
    assert month_range(2026, 12) == ("2026-12-01", "2026-12-31")


def test_quote_totals_and_codes():
    p = sample_prices()
    d = quotes.blank_draft(SETTINGS)
    assert d["serviceCharge"] == 50
    d.update(clientName="Tan family", adults=2, children=1)
    d["days"][0]["date"] = add_days(today(), 10)
    assert quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "ct01"}, p)[1] == "ok"   # ticket, lower case
    assert quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "APU"}, p)[1] == "ok"    # transfer
    assert quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "GSEN"}, p)[1] == "ok"   # guide
    assert quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "flyer"}, p)[1] == "ok"  # part of a name
    assert quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "NOPE"}, p)[1] == "err"
    lines = d["days"][0]["lines"]
    assert [l["type"] for l in lines] == ["ticket", "transport", "guide", "ticket"]
    # City tour: 2 x 14 + 1 x 10 = 38; Flyer: 2 x 45 + 29 = 119
    t = quotes.calc(d)
    assert t["tickets"] == 157 and t["transport"] == 45 and t["guides"] == 120
    assert t["total"] == 157 + 45 + 120 + 50
    assert quotes.validate(d, p)[0] == []


def test_validation_messages():
    p = sample_prices()
    d = quotes.blank_draft(SETTINGS)
    errors, _, bad = quotes.validate(d, p)
    assert "Enter the client name." in errors
    assert "Day 1: enter the date." in errors
    assert "clientName" in bad and "days.0.date" in bad
    d.update(clientName="X")
    d["days"][0]["date"] = today()
    quotes.apply_action(d, {"name": "add_meal", "day": 0, "meal": "Lunch"}, p)
    errors, _, bad = quotes.validate(d, p)
    assert "Day 1, lunch: enter the supplier." in errors
    assert "days.0.lines.0.adultPrice" in bad


def test_expired_ticket_is_blocked_and_edited_price_warns():
    p = sample_prices()
    d = quotes.blank_draft(SETTINGS)
    d.update(clientName="X")
    d["days"][0]["date"] = today()
    quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "SF01"}, p)
    d["days"][0]["lines"][0]["adultPrice"] = 40
    errors, warnings, _ = quotes.validate(d, p)
    assert not errors and any("adult price is 40.00 here" in w for w in warnings)
    assert quotes.edited_prices(d, p) == ["days.0.lines.0.adultPrice"]
    prices.find_ticket(p, "SF01")["validUntil"] = add_days(today(), -1)
    assert any("price expired" in e for e in quotes.validate(d, p)[0])
    msg, kind, _ = quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "SF01"}, p)
    assert kind == "err" and "expired" in msg


def test_group_pax_change_follows_lines():
    p = sample_prices()
    d = quotes.blank_draft(SETTINGS)
    quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "CT01"}, p)
    quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "SF01"}, p)
    d["days"][0]["lines"][1]["adults"] = 1          # changed by hand: should stay
    d["adults"] = 5
    quotes.apply_action(d, {"name": "set_pax", "field": "adults", "old": 2}, p)
    assert [l["adults"] for l in d["days"][0]["lines"]] == [5, 1]


def test_quote_numbers_include_agent():
    saved = [{"quoteNumber": "Q-20261128-AG01-001"}, {"quoteNumber": "Q-20261128-AG01-002"}, {"quoteNumber": "Q-20261128-001"}]
    assert quotes.next_quote_number(saved, "2026-11-28", "AG01") == "Q-20261128-AG01-003"
    assert quotes.next_quote_number(saved, "2026-11-28", "AG02") == "Q-20261128-AG02-001"


def test_built_quote_has_flat_lists_for_the_report():
    p = sample_prices()
    d = quotes.blank_draft(SETTINGS)
    d.update(clientName="X", group=True)
    d["days"][0]["date"] = "2026-12-17"
    quotes.apply_action(d, {"name": "add_code", "day": 0, "code": "CT01"}, p)
    d["hotels"].append({"description": "Hotel A", "supplier": "Hotel A", "amount": "300"})
    d["additional"].append({"description": "Coach", "supplier": "Bus Co", "amount": 100})
    q = quotes.build_quote(d, SETTINGS)
    assert q["tickets"][0]["travelDate"] == "2026-12-17" and q["tickets"][0]["pax"] == 2
    assert q["quoteType"] == "group" and q["subtotalAdditional"] == 100 and q["total"] == 28 + 300 + 100 + 50
    assert q["hotels"][0]["amount"] == 300.0


def test_old_format_quote_opens():
    old = {"id": "a", "quoteNumber": "Q-1", "date": "2026-01-01", "clientName": "Old",
           "tickets": [{"code": "CT01", "name": "City tour", "supplier": "S", "travelDate": "2026-01-03", "pax": 3, "unitPrice": 10}],
           "transport": [{"description": "Bus", "supplier": "T", "date": "2026-01-02", "qty": 1, "unitPrice": 50}]}
    d = quotes.draft_from_quote(old)
    assert [day["date"] for day in d["days"]] == ["2026-01-02", "2026-01-03"]
    assert d["days"][1]["lines"][0]["adults"] == 3


def test_invoice_totals_and_checks():
    d = invoices.blank_draft([], {}, "AG01", {"currency": "SGD", "businessName": "Biz"})
    assert d["invoiceNumber"].endswith("-AG01-001") and d["companyName"] == "Biz"
    d.update(clientName="ACME", discount=10, taxRate=9,
             items=[{"description": "Package", "qty": 2, "unitPrice": 450}, {"description": "Transfer", "qty": 1, "unitPrice": 60}])
    t = invoices.calc(d)
    assert t == {"subtotal": 960, "discount": 10, "rate": 9, "tax": 85.5, "total": 1035.5}
    assert invoices.validate(d, [])[0] == []
    d["items"][0]["qty"] = 0
    d["discount"] = 5000
    errors, bad = invoices.validate(d, [{"id": "other", "invoiceNumber": d["invoiceNumber"]}])
    assert "Line 1: quantity must be more than 0." in errors
    assert "Discount is more than the subtotal." in errors
    assert any("already used" in e for e in errors)


def test_report_matches_the_website_version():
    """Run the website's own report code (JavaScript) on the same quotes and compare."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    backup = json.loads((REPO / "tests" / "sample-backup.json").read_text())
    script = (
        "const R = require(process.argv[1]); const data = require(process.argv[2]);"
        "const r = R.buildReport(data.quotes, { from: '2000-01-01', to: '2100-12-31' });"
        "console.log(JSON.stringify({ total: r.supplierTotalCents, service: r.serviceChargeCents, quotes: r.quoteCount,"
        " lines: r.lines.map((l) => [l.supplier, l.type, l.reportDate, l.totalCents, l.qty]) }));"
    )
    out = subprocess.run([node, "-e", script, str(REPO / "supplier-report.js"), str(REPO / "tests" / "sample-backup.json")],
                         capture_output=True, text=True, check=True).stdout
    js = json.loads(out)
    py = report.build_report(backup["quotes"], "2000-01-01", "2100-12-31")
    assert py["supplierTotalCents"] == js["total"]
    assert py["serviceChargeCents"] == js["service"]
    assert py["quoteCount"] == js["quotes"]
    assert sorted([l["supplier"], l["type"], l["reportDate"], l["totalCents"], l["qty"]] for l in py["lines"]) == sorted(js["lines"])


def test_report_csv():
    q = {"id": "1", "quoteNumber": "Q-1", "date": "2026-12-01", "clientName": "=cmd", "serviceCharge": 10,
         "tickets": [{"code": "A", "name": "T", "supplier": "S", "travelDate": "2026-12-05", "pax": 3, "adults": 2,
                      "children": 1, "adultPrice": 10, "childPrice": 5, "unitPrice": 8.33, "total": 25}]}
    r = report.build_report([q], "2026-12-01", "2026-12-31")
    assert r["supplierTotalCents"] == 2500 and r["serviceChargeCents"] == 1000
    csv_text = report.to_csv(r["lines"])
    assert csv_text.startswith("﻿Supplier,") and "'=cmd" in csv_text and ",25.00," in csv_text
    with pytest.raises(ValueError):
        report.build_report([q], "2026-12-31", "2026-12-01")
