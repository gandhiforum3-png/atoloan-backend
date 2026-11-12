"""
Cloudflare Turnstile check for the anonymous entry point (/auth/request-code),
and the client-IP lookup also used by /findback.
"""
import asyncio
import logging
from urllib.parse import urlparse

import requests
from fastapi import HTTPException, Request

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def client_ip(request: Request) -> str | None:
    # ingress-nginx sets X-Real-IP to the connecting address (not client-controlled)
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


async def verify_captcha(token: object, client_ip: str | None) -> None:
    """Cloudflare Turnstile check for anonymous callers. No-op when
    TURNSTILE_SECRET_KEY is unset locally; in a deployed env (APP_ENV set)
    a missing secret refuses the request instead of silently skipping the check."""
    settings = get_settings()
    secret = settings.turnstile_secret_key
    if not secret:
        if settings.app_env not in ("", "local"):
            logger.error("TURNSTILE_SECRET_KEY is not set in %s — refusing anonymous requests", settings.app_env)
            raise HTTPException(status_code=503, detail="service temporarily unavailable")
        return
    if not token:
        raise HTTPException(status_code=400, detail="captcha is required")
    try:
        resp = await asyncio.to_thread(
            requests.post,
            _TURNSTILE_VERIFY_URL,
            data={"secret": secret, "response": str(token), "remoteip": client_ip or ""},
            timeout=10,
        )
        result = resp.json()
        # the token must have been minted on one of our own frontends
        ok = (
            result.get("success") is True
            and result.get("action") == "login"  # set on the widget in Turnstile.jsx
            and result.get("hostname") in {urlparse(o).hostname for o in settings.cors_origins_list}
        )
    except Exception as exc:
        logger.exception("captcha verification failed")
        raise HTTPException(status_code=503, detail="captcha verification unavailable") from exc
    if not ok:
        raise HTTPException(status_code=403, detail="captcha verification failed")
