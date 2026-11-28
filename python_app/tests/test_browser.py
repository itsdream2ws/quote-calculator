"""Clicks through the real pages in a browser (Chromium, via Playwright), against the pretend
Supabase. Skipped when Playwright is not installed. Screenshots go to tests/screenshots/."""
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

import config
from conftest import PASSWORD
from helpers import today, add_days

playwright = pytest.importorskip("playwright.sync_api")
SHOTS = Path(__file__).parent / "screenshots"


@pytest.fixture()
def site(fake, monkeypatch):
    import app as app_module
    app_module.app.testing = False
    server = make_server(config.HOST, 0, app_module.app, threaded=True)
    monkeypatch.setattr(config, "PORT", server.server_port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://{config.HOST}:{server.server_port}"
    server.shutdown()
    app_module.app.testing = True


def test_make_a_quote_in_the_browser(site, fake):
    SHOTS.mkdir(exist_ok=True)
    with playwright.sync_playwright() as pw:
        import os
        exe = os.environ.get("QC_CHROMIUM")  # e.g. /opt/pw-browsers/chromium when Playwright's own browser is missing
        try:
            browser = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        except Exception as e:  # Playwright is installed but its browser isn't (run: playwright install chromium)
            pytest.skip(f"no browser for Playwright: {e}")
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(site + "/")
        page.fill("input[name=agent]", "AG01")
        page.fill("input[name=password]", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url(site + "/quote")
        page.goto(site + "/settings")
        page.once("dialog", lambda d: d.accept())
        page.click("text=Load sample price list")
        page.wait_for_selector("text=Sample price list added")

        page.goto(site + "/quote?new=1")
        page.fill("[data-path=clientName]", "Tan family")
        page.fill("[data-path=adults]", "3")
        page.locator("[data-path=adults]").dispatch_event("change")
        page.wait_for_timeout(300)
        page.fill("[data-path='days.0.date']", add_days(today(), 5))
        for code in ("CT01", "APU", "gsen"):
            page.fill(".code-in[data-day='0']", code)
            page.press(".code-in[data-day='0']", "Enter")
            page.wait_for_selector(f"[data-day-msg='0'].ok")
        page.click("text=+ Lunch")
        page.wait_for_selector("[data-path='days.0.lines.3.supplier']")
        page.fill("[data-path='days.0.lines.3.supplier']", "Kopitiam")
        page.fill("[data-path='days.0.lines.3.adultPrice']", "10")
        page.fill("[data-path='days.0.lines.3.childPrice']", "0")
        page.click("text=+ Add hotel")
        page.fill("[data-path='hotels.0.description']", "Grand Central")
        page.fill("[data-path='hotels.0.amount']", "500")
        page.fill("[data-path=serviceCharge]", "100")
        page.wait_for_timeout(600)
        # 3 adults: city tour 42 + pickup 45 + guide 120 + lunch 30 + hotel 500 + profit 100
        assert page.text_content("[data-out=tGrand]") == "SGD 837.00"
        page.screenshot(path=str(SHOTS / "quote-page.png"), full_page=True)

        page.click("button.big[data-save]")
        page.wait_for_selector("#saveMsg.ok")
        assert "Saved as Q-" in page.text_content("#saveMsg")
        assert len(fake.tables["quotes"]) == 1
        with page.expect_download() as dl:
            page.click("button[data-save=pdf]")
        assert dl.value.suggested_filename.endswith("_Tan_family.pdf")
        assert len(fake.tables["quotes"]) == 1           # saving again updated, not duplicated

        page.reload()                                    # the open quote survives a refresh
        page.wait_for_timeout(800)
        assert page.input_value("[data-path=clientName]") == "Tan family"
        page.click("[data-preview]")
        page.wait_for_function("document.querySelector('.preview-img').naturalWidth > 0")

        page.goto(site + "/invoice?new=1")
        page.click("button.big[data-save]")              # empty: the problems are listed
        page.wait_for_selector("#saveMsg.err")
        assert "Enter your company name." in page.text_content("#errors")
        page.fill("[data-path=companyName]", "Horeb Tours")
        page.fill("[data-path=clientName]", "ACME")
        page.fill("[data-path='items.0.description']", "Package")
        page.fill("[data-path='items.0.unitPrice']", "200")
        page.click("text=+ Add line")
        page.wait_for_selector("[data-path='items.1.description']")
        page.fill("[data-path='items.1.description']", "Transfer")
        page.fill("[data-path='items.1.unitPrice']", "50")
        page.wait_for_timeout(500)
        assert page.text_content("[data-out=invGrand]") == "SGD 250.00"
        page.click("button.big[data-save]")
        page.wait_for_selector("#saveMsg.ok")
        assert len(fake.tables["invoices"]) == 1

        page.goto(site + f"/report?month={add_days(today(), 5)[:7]}")
        assert page.locator("text=City Tours Co").count() >= 1
        page.screenshot(path=str(SHOTS / "report.png"), full_page=True)

        phone = browser.new_page(viewport={"width": 390, "height": 844}, storage_state=page.context.storage_state())
        phone.goto(site + "/quote")
        phone.wait_for_timeout(800)
        assert phone.evaluate("document.documentElement.scrollWidth") <= 400
        phone.screenshot(path=str(SHOTS / "quote-phone.png"), full_page=True)
        browser.close()
        assert errors == []
