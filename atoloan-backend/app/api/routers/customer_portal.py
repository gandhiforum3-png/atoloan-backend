"""
The signed-in customer's own account: their applications, profile edits, and
closing the account.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.customer_session import clear_session_cookie, get_current_customer
from app.db import get_engine
from app.services.customer_accounts import ProfileUpdate, close_account, list_customer_applications, update_profile
from app.services.customer_auth import normalize_email

router = APIRouter(tags=["customer-portal"])


class CloseAccountIn(BaseModel):
    confirm_email: str = Field(max_length=320)


@router.get("/me/applications")
async def my_applications(customer: dict = Depends(get_current_customer)) -> list[dict]:
    async with get_engine().connect() as conn:
        return await list_customer_applications(conn, customer["email"])


@router.patch("/me")
async def update_me(changes: ProfileUpdate, customer: dict = Depends(get_current_customer)) -> dict:
    async with get_engine().begin() as conn:
        _, after = await update_profile(conn, customer["email"], changes)
    return after


@router.post("/me/close")
async def close_me(payload: CloseAccountIn, response: Response, customer: dict = Depends(get_current_customer)) -> dict:
    # Typing the address back is the confirmation — a stray click can't close the account
    if normalize_email(payload.confirm_email) != customer["email"]:
        raise HTTPException(status_code=400, detail="type your account email to confirm")
    async with get_engine().begin() as conn:
        await close_account(conn, customer["email"])
    clear_session_cookie(response)
    return {"status": "closed"}
