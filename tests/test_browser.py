"""Opt-in browser regressions; run FOODLOGGER_RUN_BROWSER_TESTS=1 pytest -m browser."""

import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.getenv("FOODLOGGER_RUN_BROWSER_TESTS") != "1", reason="Opt-in browser tests"
    ),
]


@pytest.fixture
def browser_page(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "FOODLOGGER_DB": str(tmp_path / "browser.sqlite3")}
    process = subprocess.Popen(
        [sys.executable, "-m", "foodlogger.cli", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/api/health", timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("Browser-test server did not start")
        with playwright.sync_playwright() as p:
            options = {"headless": True}
            if executable := os.getenv("FOODLOGGER_CHROMIUM"):
                options["executable_path"] = executable
            browser = p.chromium.launch(**options)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            account = page.request.post(
                url + "/api/auth/register",
                data={"username": "browseruser", "password": "browser-test-password"},
                headers={"X-FoodLogger-Request": "1"},
            )
            assert account.status == 201
            page.goto(url, wait_until="networkidle")
            yield page
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_save_locks_form_until_request_finishes(browser_page):
    from playwright.sync_api import expect

    page = browser_page
    pending = []
    page.route("**/api/meals", lambda route: pending.append(route))
    page.locator("#food-select").select_option("banana")
    page.locator("#save-meal").click()
    expect(page.locator("#food-photo")).to_be_disabled()
    expect(page.locator("#food-select")).to_be_disabled()
    expect(page.locator("#grams")).to_be_disabled()
    assert len(pending) == 1
    pending[0].continue_()
    expect(page.locator("#food-photo")).to_be_enabled()
    expect(page.locator("#meal-count")).to_have_text("1")


def test_empty_date_clears_stale_results_and_disables_export(browser_page):
    from playwright.sync_api import expect

    page = browser_page
    page.locator("#food-select").select_option("banana")
    page.locator("#save-meal").click()
    expect(page.locator("#meal-count")).to_have_text("1")
    page.locator("#journal-date").fill("")
    page.locator("#journal-date").dispatch_event("change")
    expect(page.locator("#total-calories")).to_have_text("—")
    expect(page.locator("#journal-entries")).to_be_empty()
    expect(page.locator("#export-button")).not_to_have_attribute("href")


def test_manual_journal_round_trip_and_mobile_layout(browser_page):
    from playwright.sync_api import expect

    page = browser_page
    page.locator("#food-select").select_option("banana")
    page.locator("#grams").fill("150")
    page.locator("#save-meal").click()
    expect(page.locator("#total-calories")).to_have_text("133.5")
    page.reload(wait_until="networkidle")
    expect(page.locator("#meal-count")).to_have_text("1")
    with page.expect_download() as download:
        page.locator("#export-button").click()
    assert download.value.suggested_filename.startswith("foodlogger-")
    page.set_viewport_size({"width": 390, "height": 844})
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    page.get_by_role("button", name="Delete Banana").click()
    expect(page.locator("#meal-count")).to_have_text("0")
    expect(page.locator("#empty-journal")).to_be_visible()


def test_signup_logout_login_and_private_journal(browser_page):
    from playwright.sync_api import expect

    page = browser_page
    page.locator("#logout-button").click()
    expect(page.locator("#save-meal")).to_be_disabled()
    page.locator("#welcome-signin").click()
    page.locator("#username").fill("newuser")
    page.locator("#password").fill("a-very-long-password")
    page.locator("#auth-submit").click()
    expect(page.locator("#recovery-dialog")).to_be_visible()
    assert len(page.locator("#saved-recovery").inner_text()) >= 40
    page.locator("#close-recovery").click()
    page.locator("#food-select").select_option("banana")
    page.locator("#save-meal").click()
    expect(page.locator("#meal-count")).to_have_text("1")
    page.locator("#logout-button").click()
    expect(page.locator("#journal-entries")).to_be_empty()
    expect(page.locator("#saved-recovery")).to_be_empty()
    page.locator("#account-button").click()
    page.locator("#username").fill("browseruser")
    page.locator("#password").fill("browser-test-password")
    page.locator("#auth-submit").click()
    expect(page.locator("#auth-dialog")).not_to_be_visible()
    expect(page.locator("#meal-count")).to_have_text("0")
    expect(page.locator("#journal-entries")).to_be_empty()


def test_barcode_photo_review_custom_nutrition_and_missing_product(browser_page):
    from io import BytesIO

    import barcode
    from barcode.writer import ImageWriter
    from playwright.sync_api import expect

    page = browser_page
    product = {
        "barcode": "5901234123457",
        "name": "Protein pudding",
        "brand": "Test brand",
        "quantity": "200 g",
        "basis_unit": "g",
        "serving_quantity": 200,
        "nutrition": {"calories": 75, "protein": 10, "carbs": 6, "fat": 1, "salt": 0.1},
        "raw_nutriments": {"calcium_100g": 0.2, "nutrition-score-fr_100g": -1},
        "nutriment_units": {"calcium_unit": "mg"},
        "missing_nutrients": ["sugars", "fiber"],
        "notes": [],
    }
    page.route("**/api/products/*", lambda route: route.fulfill(json=product))
    page.locator('[data-mode="barcode"]').click()
    expect(page.locator("#barcode-camera")).to_have_attribute("capture", "environment")
    image = BytesIO()
    barcode.get("ean13", "590123412345", writer=ImageWriter()).write(image)
    page.locator("#barcode-photo").set_input_files(
        {"name": "barcode.png", "mimeType": "image/png", "buffer": image.getvalue()}
    )
    expect(page.locator("#product-name")).to_have_value("Protein pudding")
    expect(page.locator("#barcode-number")).to_have_value("5901234123457")
    expect(page.locator("#nutrient-sugars")).to_have_value("")
    expect(page.locator("#grams")).to_have_value("200")
    page.locator("#save-meal").click()
    expect(page.locator("#total-protein")).to_have_text("20")
    page.reload(wait_until="networkidle")
    expect(page.locator("#meal-count")).to_have_text("1")
    page.get_by_text("Nutrition details", exact=True).click()
    expect(page.locator("#journal-entries")).to_contain_text("Not supplied")
    page.locator('[data-mode="barcode"]').click()
    page.locator("#barcode-number").fill("5901234123457")
    page.locator("#lookup-button").click()
    expect(page.locator("#product-name")).to_have_value("Protein pudding")
    page.unroute("**/api/products/*")
    page.route(
        "**/api/products/*",
        lambda route: route.fulfill(status=404, json={"detail": "Product not found."}),
    )
    page.locator("#lookup-button").click()
    expect(page.locator("#barcode-status")).to_contain_text("Product not found")
    expect(page.locator("#product-name")).to_have_value("")
    expect(page.locator("#nutrient-protein")).to_have_value("")
    page.locator('[data-mode="manual"]').click()
    page.locator("#product-name").fill("My drink")
    page.locator("#basis-unit").select_option("ml")
    for key, value in {"calories": "50", "protein": "5", "carbs": "6", "fat": "1"}.items():
        page.locator(f"#nutrient-{key}").fill(value)
    page.locator("#grams").fill("250")
    page.locator("#save-meal").click()
    expect(page.locator("#meal-count")).to_have_text("2")
    expect(page.locator("#total-protein")).to_have_text("32.5")
    expect(page.locator("#journal-entries")).to_contain_text("250 ml")
    page.set_viewport_size({"width": 390, "height": 844})
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")


def test_day_dial_follows_the_journal_and_every_width_fits(browser_page):
    from playwright.sync_api import expect

    page = browser_page
    expect(page.locator("#dial-dots circle")).to_have_count(0)
    page.locator("#food-select").select_option("banana")
    page.locator("#meal-type").select_option("breakfast")
    page.locator("#save-meal").click()
    expect(page.locator("#dial-dots circle.breakfast")).to_have_count(1)
    expect(page.locator(".meal-group-title.breakfast")).to_have_text("Breakfast")
    assert (
        page.locator("#share-carbs").evaluate("el => Number(el.style.getPropertyValue('--share'))")
        > 0
    )
    for width, height in [(390, 844), (768, 1024), (1440, 900)]:
        page.set_viewport_size({"width": width, "height": height})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    page.get_by_role("button", name="Delete Banana").click()
    expect(page.locator("#dial-dots circle")).to_have_count(0)
