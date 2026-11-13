from fastapi.testclient import TestClient

from foodlogger.app import create_app


def register(client, name):
    response = client.post(
        "/api/auth/register",
        json={
            "username": name,
            "password": "long-enough-password-2026",
        },
        headers={"X-FoodLogger-Request": "1"},
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


def test_authentication_required_and_two_accounts_cannot_read_or_delete_each_others_meals(tmp_path):
    app = create_app(tmp_path / "shared.sqlite3")
    with TestClient(app) as alice, TestClient(app) as bob:
        assert alice.get("/api/meals?day=2026-10-08").status_code == 401
        register(alice, "alice")
        register(bob, "bob")
        meal = {"food_id": "banana", "grams": 150, "day": "2026-10-08", "meal_type": "snack"}
        saved = alice.post("/api/meals", json=meal)
        assert saved.status_code == 201, saved.text
        assert alice.get("/api/meals?day=2026-10-08").json()["summary"]["calories"] == 133.5
        assert bob.get("/api/meals?day=2026-10-08").json()["meals"] == []
        assert "Banana" not in bob.get("/api/export?day=2026-10-08").text
        assert bob.delete("/api/meals/" + saved.json()["id"]).status_code == 404
        assert alice.delete("/api/meals/" + saved.json()["id"]).status_code == 204


def test_csrf_cross_origin_logout_and_cookie_settings(tmp_path):
    with TestClient(create_app(tmp_path / "app.sqlite3")) as client:
        info = register(client, "alice")
        assert client.cookies.get("foodlogger_session")
        meal = {"food_id": "banana", "grams": 150, "day": "2026-10-08", "meal_type": "snack"}
        client.headers.pop("X-CSRF-Token")
        assert client.post("/api/meals", json=meal).status_code == 403
        client.headers["X-CSRF-Token"] = info["csrf_token"]
        assert (
            client.post(
                "/api/meals", json=meal, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").status_code == 401


def test_custom_product_roundtrip_preserves_nutrients_and_csv_is_safe(tmp_path):
    with TestClient(create_app(tmp_path / "app.sqlite3")) as client:
        register(client, "alice")
        payload = {
            "name": "=1+1",
            "grams": 200,
            "basis_unit": "g",
            "day": "2026-10-08",
            "meal_type": "snack",
            "nutrition": {
                "calories": 75,
                "protein": 10,
                "carbs": 6,
                "fat": 1,
                "sugars": 4,
                "salt": 0.1,
            },
            "raw_nutriments": {"calcium_100g": 0.2},
        }
        saved = client.post("/api/meals/custom", json=payload)
        assert saved.status_code == 201, saved.text
        assert saved.json()["protein"] == 20
        stored = client.get("/api/meals?day=2026-10-08").json()["meals"][0]
        assert stored["details"]["nutrition_total"]["sugars"] == 8
        assert stored["details"]["raw_nutriments"]["calcium_100g"] == 0.2
        assert "'=1+1" in client.get("/api/export?day=2026-10-08").text


def test_auth_responses_are_not_cached_and_registration_rejects_simple_cross_site_requests(
    tmp_path,
):
    with TestClient(create_app(tmp_path / "app.sqlite3")) as client:
        assert (
            client.post(
                "/api/auth/register",
                json={
                    "username": "alice",
                    "password": "long-enough-password-2026",
                },
            ).status_code
            == 403
        )
        register(client, "alice")
        response = client.get("/api/auth/me")
        assert response.headers["cache-control"] == "no-store"
        assert "csrf_token" in response.json()
        assert "password" not in response.text


def test_recovery_invalidates_old_sessions(tmp_path):
    app = create_app(tmp_path / "app.sqlite3")
    with TestClient(app) as old, TestClient(app) as recovery:
        account = register(old, "alice")
        response = recovery.post(
            "/api/auth/recover",
            json={
                "username": "alice",
                "recovery_code": account["recovery_code"],
                "new_password": "a-different-long-password",
            },
            headers={"X-FoodLogger-Request": "1"},
        )
        assert response.status_code == 200, response.text
        assert old.get("/api/auth/me").status_code == 401
        assert recovery.get("/api/auth/me").status_code == 200


def test_login_rate_limit(tmp_path):
    with TestClient(create_app(tmp_path / "app.sqlite3")) as client:
        for _ in range(10):
            result = client.post(
                "/api/auth/login",
                json={
                    "username": "unknown",
                    "password": "not-a-real-password",
                },
                headers={"X-FoodLogger-Request": "1"},
            )
        assert result.status_code == 429


def test_product_lookup_statuses_and_upload_are_authenticated(tmp_path):
    import httpx

    from foodlogger.products import OpenFoodFactsClient

    def upstream(request):
        if "5901234123457" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "status": 1,
                    "product": {
                        "code": "5901234123457",
                        "product_name": "Protein pudding",
                        "nutriments": {
                            "energy-kcal_100g": 75,
                            "proteins_100g": 10,
                            "carbohydrates_100g": 6,
                            "fat_100g": 1,
                        },
                    },
                },
            )
        return httpx.Response(200, json={"status": 0})

    products = OpenFoodFactsClient(transport=httpx.MockTransport(upstream))
    with TestClient(create_app(tmp_path / "app.sqlite3", products=products)) as client:
        assert client.get("/api/products/5901234123457").status_code == 401
        assert client.post("/api/barcode/scan", files={"file": ("x.png", b"x")}).status_code == 401
        register(client, "alice")
        result = client.get("/api/products/5901234123457")
        assert result.status_code == 200
        assert result.json()["nutrition"]["protein"] == 10
        assert result.json()["nutrition"]["fiber"] is None
        assert client.get("/api/products/4006381333931").status_code == 404
        assert client.get("/api/products/5901234123451").status_code == 422
        assert client.post("/api/barcode/scan", files={"file": ("x.png", b"x")}).status_code == 422


def test_production_cookie_host_and_origin(tmp_path):
    from foodlogger.security import Settings

    settings = Settings(production=True, public_url="https://food.example")
    with TestClient(
        create_app(tmp_path / "prod.sqlite3", settings=settings), base_url="https://food.example"
    ) as client:
        result = client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "long-test-password"},
            headers={"X-FoodLogger-Request": "1", "Origin": "https://food.example"},
        )
        assert result.status_code == 201
        cookie = result.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
        assert client.get("/api/auth/me").status_code == 200
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
        assert "max-age=" in result.headers["strict-transport-security"]


def test_proxy_client_ip_does_not_trust_spoofed_left_prefixes():
    from starlette.requests import Request

    from foodlogger.security import Settings

    request = Request(
        {
            "type": "http",
            "client": ("10.0.0.2", 8000),
            "headers": [(b"x-forwarded-for", b"198.51.100.5, 203.0.113.17")],
        }
    )
    assert Settings().client_address(request) == "10.0.0.2"
    assert Settings(trusted_proxy_hops=1).client_address(request) == "203.0.113.17"


def test_production_requires_https_and_persistent_path(monkeypatch):
    import pytest

    from foodlogger.security import Settings

    monkeypatch.setenv("FOODLOGGER_ENV", "production")
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.setenv("FOODLOGGER_PUBLIC_URL", "http://food.example")
    with pytest.raises(RuntimeError, match="HTTPS"):
        Settings.from_environment()
    monkeypatch.setenv("FOODLOGGER_PUBLIC_URL", "https://food.example")
    monkeypatch.setenv("FOODLOGGER_DB", "runtime/journal.sqlite3")
    with pytest.raises(RuntimeError, match="absolute"):
        Settings.from_environment()
    monkeypatch.setenv("FOODLOGGER_DB", "/var/data/foodlogger/journal.sqlite3")
    assert Settings.from_environment().production


def test_image_work_is_bounded_across_barcode_and_prediction(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from io import BytesIO
    from threading import Event

    from PIL import Image

    entered, release = Event(), Event()

    class PausedClassifier:
        name = "test"

        def predict(self, image):
            entered.set()
            assert release.wait(timeout=5)
            return {"status": "uncertain", "candidates": []}

    picture = BytesIO()
    Image.new("RGB", (50, 50), "white").save(picture, format="PNG")
    with TestClient(create_app(tmp_path / "app.sqlite3", PausedClassifier())) as client:
        register(client, "alice")
        with ThreadPoolExecutor() as executor:
            running = executor.submit(
                client.post, "/api/predict", files={"file": ("x.png", picture.getvalue())}
            )
            try:
                assert entered.wait(timeout=5)
                response = client.post(
                    "/api/barcode/scan", files={"file": ("x.png", picture.getvalue())}
                )
                assert response.status_code == 429
            finally:
                release.set()
            assert running.result(timeout=5).status_code == 200
        # Slot released on success and errors, so normal validation still works.
        assert (
            client.post("/api/barcode/scan", files={"file": ("x.png", b"bad")}).status_code == 422
        )
        assert (
            client.post("/api/predict", files={"file": ("x.png", picture.getvalue())}).status_code
            == 200
        )


def test_wrong_passwords_from_one_address_do_not_lock_the_account_for_others(tmp_path):
    app = create_app(tmp_path / "app.sqlite3")
    headers = {"X-FoodLogger-Request": "1"}
    password = "long-enough-password-2026"
    with (
        TestClient(app, client=("198.51.100.7", 4000)) as attacker,
        TestClient(app, client=("203.0.113.9", 5000)) as owner,
    ):
        register(owner, "alice")
        owner.cookies.clear()
        wrong = {"username": "alice", "password": "not-the-right-password"}
        codes = [
            attacker.post("/api/auth/login", json=wrong, headers=headers).status_code
            for _ in range(10)
        ]
        assert codes[0] == 401 and codes[-1] == 429
        response = owner.post(
            "/api/auth/login", json={"username": "alice", "password": password}, headers=headers
        )
        assert response.status_code == 200, response.text


def test_account_deletion_rejects_an_oversized_body_before_reading_it(tmp_path):
    with TestClient(create_app(tmp_path / "app.sqlite3")) as client:
        body = b'{"password":"' + b"a" * 200_000 + b'","confirmation":"DELETE"}'
        response = client.request(
            "DELETE",
            "/api/auth/account",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        register(client, "alice")
        response = client.request(
            "DELETE",
            "/api/auth/account",
            json={"password": "long-enough-password-2026", "confirmation": "DELETE"},
        )
        assert response.status_code == 204
