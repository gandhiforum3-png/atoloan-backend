"""
Customer sign-in with an emailed one-time code, sign-out, and the signed-in
profile. Request-code answers the same way whether or not the email can sign
in, so it can't be used to discover who has an account.
"""
import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.captcha import client_ip, verify_captcha
from app.core.customer_session import (
    CUSTOMER_COOKIE,
    clear_session_cookie,
    get_current_customer,
    set_session_cookie,
)
from app.db import get_engine
from app.integrations.email import send_disabled_notice, send_login_code
from app.services.customer_auth import (
    CodeRateLimited,
    create_session,
    issue_code,
    normalize_email,
    resolve_session,
    revoke_session,
    verify_code,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["customer-auth"])

# No email-validator dependency: a shape check is enough — the code itself
# proves the address works.
_EMAIL = Field(max_length=320, pattern=r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$")


class RequestCodeIn(BaseModel):
    email: str = _EMAIL
    captcha_token: str | None = Field(None, max_length=2048)  # Turnstile tokens are at most 2048 chars
    language: Literal["en", "es"] = "en"


class VerifyCodeIn(BaseModel):
    email: str = _EMAIL
    code: str = Field(pattern=r"^\d{6}$")


@router.post("/auth/request-code", status_code=202)
async def request_code(payload: RequestCodeIn, request: Request) -> dict:
    await verify_captcha(payload.captcha_token, client_ip(request))
    email = normalize_email(payload.email)
    try:
        # Sent inside the transaction: if the email fails, the new code rolls back,
        # the code already in the customer's inbox keeps working and no send is used up
        async with get_engine().begin() as conn:
            code = await issue_code(conn, email)
            if code is None:  # disabled account: tell them why, instead of a code
                await asyncio.to_thread(send_disabled_notice, email, payload.language)
            else:
                await asyncio.to_thread(send_login_code, email, code, payload.language)
    except CodeRateLimited as exc:
        raise HTTPException(status_code=429, detail="too many codes requested, try again in an hour") from exc
    except RuntimeError as exc:  # CUSTOMER_AUTH_SECRET or SES sender missing in a deployed env
        logger.error("sign-in unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="sign-in is temporarily unavailable") from exc
    except Exception as exc:
        # Type only: SES errors can quote the recipient address
        logger.error("sending sign-in email failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="we couldn't send the code, please try again") from exc
    return {"status": "sent"}


@router.post("/auth/verify-code")
async def verify(payload: VerifyCodeIn, response: Response) -> dict:
    email = normalize_email(payload.email)
    # The failed-attempt count must commit, so the 400 is raised after the transaction
    async with get_engine().begin() as conn:
        result = await verify_code(conn, email, payload.code)
        if result == "ok":
            token = await create_session(conn, email)
            profile = await resolve_session(conn, token)
    if result == "wrong":
        raise HTTPException(status_code=400, detail="invalid code")
    if result == "expired":
        raise HTTPException(status_code=410, detail="this code has expired or had too many tries — request a new one")
    if result == "locked":
        raise HTTPException(status_code=429, detail="too many wrong codes — try again tomorrow")
    set_session_cookie(response, token)
    return profile


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(CUSTOMER_COOKIE)
    if token:
        async with get_engine().begin() as conn:
            await revoke_session(conn, token)
    clear_session_cookie(response)
    return {"status": "signed out"}


@router.get("/me")
async def me(customer: dict = Depends(get_current_customer)) -> dict:
    return customer
