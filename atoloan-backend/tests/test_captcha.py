"""Turnstile check shared by the anonymous entry point (/auth/request-code)."""
import asyncio

import pytest
from fastapi import HTTPException

from app.core import captcha
from app.core.config import get_settings


def test_fails_closed_when_unconfigured_in_deployed_env(monkeypatch):
    monkeypatch.setattr(get_settings(), "turnstile_secret_key", "")
    monkeypatch.setattr(get_settings(), "app_env", "prod")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(captcha.verify_captcha(None, None))
    assert exc.value.status_code == 503


def test_skipped_locally_when_unconfigured(monkeypatch):
    monkeypatch.setattr(get_settings(), "turnstile_secret_key", "")
    monkeypatch.setattr(get_settings(), "app_env", "")
    asyncio.run(captcha.verify_captcha(None, None))  # no exception


@pytest.mark.parametrize(
    "success,hostname,action,status",
    [
        (False, "atoloans.com", "login", 403),
        (True, "evil.example", "login", 403),
        (True, None, "login", 403),
        (True, "atoloans.com", "signup", 403),
        (True, "atoloans.com", None, 403),
        (True, "atoloans.com", "login", None),
    ],
)
def test_token_checked_with_cloudflare(monkeypatch, success, hostname, action, status):
    class Resp:
        def json(self):
            return {"success": success, "hostname": hostname, "action": action}

    monkeypatch.setattr(get_settings(), "turnstile_secret_key", "secret")
    monkeypatch.setattr(get_settings(), "cors_origins", "https://atoloans.com,https://www.atoloans.com")
    monkeypatch.setattr(captcha.requests, "post", lambda *a, **k: Resp())
    if status is None:
        asyncio.run(captcha.verify_captcha("token", "203.0.113.1"))
    else:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(captcha.verify_captcha("token", "203.0.113.1"))
        assert exc.value.status_code == status
