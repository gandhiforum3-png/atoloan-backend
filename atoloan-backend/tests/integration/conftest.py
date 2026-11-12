"""
Shared fixtures for integration tests.
Loads the .env file so ANTHROPIC_API_KEY, DB credentials, etc. are available.
"""
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the inner app root (atoloan-backend/atoloan-backend/.env)
_ENV_FILE = Path(__file__).parents[2] / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)


import asyncio  # noqa: E402

import pytest  # noqa: E402

_SENT_CODES: dict[str, str] = {}


def db_available() -> bool:
    import app.db as db

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


@pytest.fixture
def sign_in(monkeypatch):
    """sign_in(client, email) → a real customer session on the TestClient
    (request-code + verify-code, with the emailed code captured)."""
    from app.api.routers import customer_auth
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "customer_cookie_secure", False)  # TestClient talks plain http
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    monkeypatch.setattr(settings, "app_env", "")
    monkeypatch.setattr(customer_auth, "send_login_code", lambda to, code, language: _SENT_CODES.__setitem__(to, code))

    def _sign_in(client, email):
        client.cookies.clear()
        assert client.post("/auth/request-code", json={"email": email}).status_code == 202
        resp = client.post("/auth/verify-code", json={"email": email, "code": _SENT_CODES[email]})
        assert resp.status_code == 200
        return resp

    return _sign_in
