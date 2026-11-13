import asyncio

from foodlogger.app import BodyLimitMiddleware


def test_upload_slot_is_reserved_before_reading_body_and_released_on_disconnect():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        responses = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = BodyLimitMiddleware(app)
        scope = {"type": "http", "method": "POST", "path": "/api/predict"}

        async def held_receive():
            entered.set()
            await release.wait()
            return {"type": "http.disconnect"}

        async def forbidden_receive():
            raise AssertionError("Rejected upload must not be buffered")

        async def send(message):
            responses.append(message)

        first = asyncio.create_task(middleware(scope, held_receive, send))
        await entered.wait()
        # Photo recognition and meal analysis share one slot; nothing is buffered.
        await middleware({**scope, "path": "/api/analyze-meal"}, forbidden_receive, send)
        assert responses[0]["status"] == 429
        responses.clear()

        async def empty_scan():
            return {"type": "http.request", "body": b"", "more_body": False}

        # Barcode scans use their own slot and are not blocked by the busy one.
        await middleware({**scope, "path": "/api/barcode/scan"}, empty_scan, send)
        assert responses[0]["status"] == 204
        release.set()
        await first
        responses.clear()

        async def empty_receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await middleware(scope, empty_receive, send)
        assert responses[0]["status"] == 204

    asyncio.run(scenario())


def test_stalled_upload_expires_and_releases_slot(monkeypatch):
    async def scenario():
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})

        middleware = BodyLimitMiddleware(app)
        middleware.body_timeout = 0.02
        responses = []

        async def stalled_receive():
            await asyncio.Event().wait()

        async def send(message):
            responses.append(message)

        scope = {"type": "http", "method": "POST", "path": "/api/predict"}
        await asyncio.wait_for(middleware(scope, stalled_receive, send), timeout=1)
        assert responses[0]["status"] == 408
        assert middleware.upload_slot.acquire(blocking=False)
        middleware.upload_slot.release()

    asyncio.run(scenario())


def test_unauthenticated_upload_is_rejected_without_reading_or_reserving():
    class Auth:
        def get_session(self, token):
            return None

    async def scenario():
        async def app(scope, receive, send):
            raise AssertionError("Unauthenticated upload reached parser")

        middleware = BodyLimitMiddleware(app, auth=Auth())
        responses = []

        async def receive():
            raise AssertionError("Unauthenticated upload body was read")

        async def send(message):
            responses.append(message)

        scope = {"type": "http", "method": "POST", "path": "/api/predict", "headers": []}
        await middleware(scope, receive, send)
        assert responses[0]["status"] == 401
        assert middleware.upload_slot.acquire(blocking=False)
        middleware.upload_slot.release()

    asyncio.run(scenario())


class SignedIn:
    """Resolve every bearer token to an account named after the token."""

    def get_session(self, token):
        return {"user": {"id": token}, "csrf_token": "unused"}


def upload_scope(user, path="/api/predict"):
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [(b"authorization", f"Bearer {user}".encode())],
    }


async def accept(scope, receive, send):
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def empty_body():
    return {"type": "http.request", "body": b"", "more_body": False}


def test_one_account_cannot_hold_both_upload_slots():
    from foodlogger.security import RateLimiter

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        middleware = BodyLimitMiddleware(accept, auth=SignedIn(), limiter=RateLimiter())
        responses = []

        async def held_receive():
            entered.set()
            await release.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            responses.append(message)

        first = asyncio.create_task(middleware(upload_scope("alice"), held_receive, send))
        await entered.wait()
        await middleware(upload_scope("alice", "/api/barcode/scan"), empty_body, send)
        assert responses[0]["status"] == 429
        responses.clear()
        await middleware(upload_scope("bob", "/api/barcode/scan"), empty_body, send)
        assert responses[0]["status"] == 204
        release.set()
        await first
        responses.clear()
        await middleware(upload_scope("alice", "/api/barcode/scan"), empty_body, send)
        assert responses[0]["status"] == 204

    asyncio.run(scenario())


def test_account_limits_apply_before_an_upload_reserves_a_slot():
    from foodlogger.security import RateLimiter

    async def scenario():
        middleware = BodyLimitMiddleware(accept, auth=SignedIn(), limiter=RateLimiter())
        responses = []

        async def send(message):
            responses.append(message)

        async def unread():
            raise AssertionError("Rate-limited upload body was read")

        scope = upload_scope("alice", "/api/analyze-meal")
        for _ in range(6):
            await middleware(scope, empty_body, send)
        assert {m["status"] for m in responses if "status" in m} == {204}
        responses.clear()
        await middleware(scope, unread, send)
        assert responses[0]["status"] == 429
        assert middleware.upload_slot.acquire(blocking=False)
        middleware.upload_slot.release()
        responses.clear()
        await middleware(upload_scope("bob", "/api/analyze-meal"), empty_body, send)
        assert responses[0]["status"] == 204

    asyncio.run(scenario())


def test_slow_uploads_use_up_an_accounts_upload_time():
    from foodlogger.app import UPLOAD_SECONDS, UPLOAD_WINDOW
    from foodlogger.security import RateLimiter

    async def scenario():
        limiter = RateLimiter()
        middleware = BodyLimitMiddleware(accept, auth=SignedIn(), limiter=limiter)
        middleware.body_timeout = 0.02
        responses = []

        async def stalled():
            await asyncio.Event().wait()

        async def send(message):
            responses.append(message)

        await middleware(upload_scope("alice"), stalled, send)
        assert responses[0]["status"] == 408
        # The stalled body was charged; an account that used its budget must wait.
        assert not limiter.allow("upload-time:alice", 0.02, UPLOAD_WINDOW, cost=0)
        limiter.charge("upload-time:alice", UPLOAD_SECONDS, UPLOAD_WINDOW)
        responses.clear()
        await middleware(upload_scope("alice"), stalled, send)
        assert responses[0]["status"] == 429
        responses.clear()
        await middleware(upload_scope("bob"), empty_body, send)
        assert responses[0]["status"] == 204

    asyncio.run(scenario())


def test_delete_bodies_are_bounded_like_other_methods():
    async def scenario():
        async def app(scope, receive, send):
            raise AssertionError("Oversized body reached the application")

        middleware = BodyLimitMiddleware(app)
        responses = []

        async def huge():
            return {"type": "http.request", "body": b"x" * 70_000, "more_body": True}

        async def send(message):
            responses.append(message)

        scope = {"type": "http", "method": "DELETE", "path": "/api/auth/account"}
        await middleware(scope, huge, send)
        assert responses[0]["status"] == 413

    asyncio.run(scenario())
