"""
/auth/request-code, /auth/verify-code, /auth/logout and GET /me end to end
against the local Postgres (skipped when unreachable). The email sender is
replaced with a capture so tests can read the code.
"""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db as db
from app.api.routers import customer_auth as auth_router
from app.core.config import get_settings
from app.main import app


def _db_available() -> bool:
    async def probe():
        try:
            await db.test_connection()
            return True
        except Exception:
            return False
        finally:
            await db.get_engine().dispose()
            db._engine = None

    return asyncio.run(probe())


pytestmark = [
    pytest.mark.skipif(not _db_available(), reason="local Postgres not reachable"),
    pytest.mark.anonymous_customer,  # real sessions here, not the unit-test stand-in
]

SENT: dict[str, str] = {}
NOTICES: list[str] = []


@pytest.fixture(scope="module")
def client():
    db._engine = None
    with TestClient(app) as c:
        yield c
    db._engine = None


@pytest.fixture(autouse=True)
def _local_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "customer_cookie_secure", False)  # TestClient talks plain http
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    monkeypatch.setattr(settings, "app_env", "")
    monkeypatch.setattr(auth_router, "send_login_code", lambda to, code, language: SENT.__setitem__(to, code))
    monkeypatch.setattr(auth_router, "send_disabled_notice", lambda to, language: NOTICES.append(to))


@pytest.fixture
def email(client):
    address = f"flow-{uuid.uuid4().hex[:10]}@example.com"
    yield address
    client.cookies.clear()

    async def cleanup():
        async with db.get_engine().begin() as conn:
            await conn.execute(text("DELETE FROM customer_login_codes WHERE email = :e"), {"e": address})
            await conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": address})

    client.portal.call(cleanup)


def _sign_in(client, email, request_as=None, verify_as=None):
    assert client.post("/auth/request-code", json={"email": request_as or email}).status_code == 202
    return client.post("/auth/verify-code", json={"email": verify_as or email, "code": SENT[email]})


def _set_status(client, email, status):
    async def go():
        async with db.get_engine().begin() as conn:
            await conn.execute(
                text("INSERT INTO users (email, first_name, last_name, status) VALUES (:e, '', '', :s) "
                     "ON CONFLICT (email) DO UPDATE SET status = :s"),
                {"e": email, "s": status},
            )

    client.portal.call(go)


def test_request_code_same_response_for_unknown_and_disabled(client, email):
    disabled = f"disabled-{uuid.uuid4().hex[:8]}@example.com"
    _set_status(client, disabled, "disabled")
    unknown = client.post("/auth/request-code", json={"email": email})
    locked = client.post("/auth/request-code", json={"email": disabled})
    assert (unknown.status_code, unknown.json()) == (locked.status_code, locked.json()) == (202, {"status": "sent"})
    assert disabled not in SENT
    assert disabled in NOTICES  # same SES round trip, and the customer learns why they can't sign in

    async def cleanup():
        async with db.get_engine().begin() as conn:
            await conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": disabled})

    client.portal.call(cleanup)


def test_request_code_requires_captcha_when_configured(client, email, monkeypatch):
    monkeypatch.setattr(get_settings(), "turnstile_secret_key", "secret")
    assert client.post("/auth/request-code", json={"email": email}).status_code == 400


def test_request_code_refused_when_deployed_without_sender(client, email, monkeypatch):
    def unconfigured(to, code, language):
        raise RuntimeError("SES_FROM_EMAIL is not set")

    monkeypatch.setattr(auth_router, "send_login_code", unconfigured)
    assert client.post("/auth/request-code", json={"email": email}).status_code == 503


def test_sixth_request_in_an_hour_is_429(client, email):
    for _ in range(5):
        assert client.post("/auth/request-code", json={"email": email}).status_code == 202
    assert client.post("/auth/request-code", json={"email": email}).status_code == 429


def test_verify_sets_httponly_lax_cookie(client, email, monkeypatch):
    monkeypatch.setattr(get_settings(), "customer_cookie_secure", True)
    resp = _sign_in(client, email)
    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"].lower()
    assert "atoloan_customer_session=" in cookie
    for attribute in ("httponly", "samesite=lax", "max-age=43200", "secure", "path=/"):
        assert attribute in cookie


def test_wrong_code_is_400(client, email):
    client.post("/auth/request-code", json={"email": email})
    wrong = f"{(int(SENT[email]) + 1) % 10**6:06d}"
    resp = client.post("/auth/verify-code", json={"email": email, "code": wrong})
    assert resp.status_code == 400
    assert "set-cookie" not in resp.headers


def test_me_requires_session(client):
    client.cookies.clear()
    resp = client.get("/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "sign in required"


def test_me_after_verify_returns_profile(client, email):
    _sign_in(client, email)
    body = client.get("/me").json()
    assert body["email"] == email
    assert set(body) == {"email", "first_name", "last_name", "phone_number", "address", "city", "state", "zipcode"}


def test_mixed_case_email_same_account(client, email):
    resp = _sign_in(client, email, request_as=f"  {email.upper()}", verify_as=f"{email.title()} ")
    assert resp.status_code == 200
    assert client.get("/me").json()["email"] == email


def test_logout_revokes(client, email):
    _sign_in(client, email)
    token = client.cookies.get("atoloan_customer_session")
    assert client.post("/auth/logout").status_code == 200
    client.cookies.set("atoloan_customer_session", token)  # replaying the old cookie
    assert client.get("/me").status_code == 401


def test_disabled_mid_session_gets_401(client, email):
    _sign_in(client, email)
    assert client.get("/me").status_code == 200
    _set_status(client, email, "disabled")
    assert client.get("/me").status_code == 401


def test_cross_origin_post_blocked(client, email):
    resp = client.post("/auth/request-code", json={"email": email}, headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403


def test_allowed_origin_gets_credentialed_cors(client, email):
    origin = get_settings().cors_origins_list[0]
    resp = client.post("/auth/request-code", json={"email": email}, headers={"Origin": origin})
    assert resp.status_code == 202
    assert resp.headers["access-control-allow-origin"] == origin
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_no_store_header(client, email):
    assert _sign_in(client, email).headers["cache-control"] == "no-store"
    assert client.get("/me").headers["cache-control"] == "no-store"


def test_failed_send_keeps_the_previous_code(client, email, monkeypatch):
    assert client.post("/auth/request-code", json={"email": email}).status_code == 202
    first_code = SENT[email]

    def ses_down(to, code, language):
        raise ConnectionError("SES unreachable")

    monkeypatch.setattr(auth_router, "send_login_code", ses_down)
    assert client.post("/auth/request-code", json={"email": email}).status_code == 502

    resp = client.post("/auth/verify-code", json={"email": email, "code": first_code})
    assert resp.status_code == 200  # the code already in their inbox still works


def test_burnt_code_says_request_a_new_one(client, email):
    client.post("/auth/request-code", json={"email": email})
    right = SENT[email]
    wrong = f"{(int(right) + 1) % 10**6:06d}"
    for _ in range(5):
        assert client.post("/auth/verify-code", json={"email": email, "code": wrong}).status_code == 400
    resp = client.post("/auth/verify-code", json={"email": email, "code": right})
    assert resp.status_code == 410
    assert "request a new" in resp.json()["detail"]
