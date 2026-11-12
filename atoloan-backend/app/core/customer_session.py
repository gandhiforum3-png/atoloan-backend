"""
Customer session cookie: resolve it per request, set it on sign-in, clear it
on sign-out. The cookie holds a random token; only its hash is stored.
"""
from fastapi import Depends, HTTPException, Request, Response

from app.core.config import get_settings
from app.db import get_engine
from app.services.customer_auth import SESSION_TTL, resolve_session

CUSTOMER_COOKIE = "atoloan_customer_session"


async def optional_customer(request: Request) -> dict | None:
    token = request.cookies.get(CUSTOMER_COOKIE)
    if not token:
        return None
    async with get_engine().connect() as conn:
        return await resolve_session(conn, token)


async def get_current_customer(customer: dict | None = Depends(optional_customer)) -> dict:
    if customer is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return customer


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=CUSTOMER_COOKIE,
        value=token,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        secure=get_settings().customer_cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=CUSTOMER_COOKIE, path="/", httponly=True, secure=get_settings().customer_cookie_secure, samesite="lax"
    )
