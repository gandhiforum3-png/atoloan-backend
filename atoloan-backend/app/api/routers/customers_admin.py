"""
Customer accounts for atoloan admins. Service token only: dealer-hub-backend
enforces admin rights and writes the audit log before calling these.

An account is a users row that has signed in at least once — older guest and
dealer-entered rows never proved they own the email. Accounts are addressed by
their numeric id: an email in a URL would end up in every access log.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dependencies import get_conn
from app.core.security import require_service_token
from app.models.customer_tables import customer_sessions_table as sessions
from app.models.loan_application_table import loan_applications_table as la
from app.models.user_table import user_table as users
from app.services.customer_accounts import ProfileUpdate, close_account, list_customer_applications, update_profile
from app.services.customer_auth import revoke_all_sessions

router = APIRouter(prefix="/customers", tags=["customers-admin"], dependencies=[Depends(require_service_token)])

_ACTIVE_SESSIONS = (
    select(func.count())
    .where(sessions.c.email == users.c.email, sessions.c.revoked_at.is_(None), sessions.c.expires_at > func.now())
    .scalar_subquery()
    .label("active_sessions")
)
_APPLICATIONS = select(func.count()).where(la.c.customer_email == users.c.email).scalar_subquery().label("applications")
_COLUMNS = [
    users.c.id,
    users.c.email,
    users.c.first_name,
    users.c.last_name,
    users.c.phone_number,
    users.c.status,
    users.c.created_at,
    users.c.last_login_at,
    _ACTIVE_SESSIONS,
    _APPLICATIONS,
]
_IS_ACCOUNT = users.c.last_login_at.is_not(None)


class StatusIn(BaseModel):
    status: Literal["active", "disabled"]


async def _account(conn: AsyncConnection, customer_id: int) -> dict:
    row = (
        await conn.execute(
            select(*_COLUMNS, users.c.address, users.c.city, users.c.state, users.c.zipcode).where(
                users.c.id == customer_id, _IS_ACCOUNT
            )
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return dict(row)


@router.get("")
async def list_customers(
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: AsyncConnection = Depends(get_conn),
) -> dict:
    where = [_IS_ACCOUNT]
    if q and q.strip():
        term = q.strip()
        where.append(
            or_(
                (users.c.first_name + " " + users.c.last_name).icontains(term, autoescape=True),
                users.c.email.icontains(term, autoescape=True),
                users.c.phone_number.icontains(term, autoescape=True),
            )
        )
    rows = (
        await conn.execute(
            select(*_COLUMNS).where(*where).order_by(users.c.created_at.desc(), users.c.email).limit(limit).offset(offset)
        )
    ).mappings().all()
    total = await conn.scalar(select(func.count()).select_from(users).where(*where))
    return {"customers": [dict(row) for row in rows], "total": total}


@router.get("/{customer_id}")
async def get_customer(customer_id: int, conn: AsyncConnection = Depends(get_conn)) -> dict:
    account = await _account(conn, customer_id)
    return {**account, "applications": await list_customer_applications(conn, account["email"])}


@router.patch("/{customer_id}")
async def update_customer(customer_id: int, changes: ProfileUpdate, conn: AsyncConnection = Depends(get_conn)) -> dict:
    account = await _account(conn, customer_id)
    before, after = await update_profile(conn, account["email"], changes)
    return {"before": before, "after": after}


@router.post("/{customer_id}/status")
async def set_customer_status(customer_id: int, payload: StatusIn, conn: AsyncConnection = Depends(get_conn)) -> dict:
    account = await _account(conn, customer_id)
    await conn.execute(update(users).where(users.c.id == customer_id).values(status=payload.status))
    if payload.status == "disabled":
        # Signed out everywhere now, not when the 12h sessions would expire
        await revoke_all_sessions(conn, account["email"])
    return {"id": customer_id, "email": account["email"], "status": payload.status, "previous_status": account["status"]}


@router.post("/{customer_id}/close")
async def close_customer(customer_id: int, conn: AsyncConnection = Depends(get_conn)) -> dict:
    account = await _account(conn, customer_id)
    await close_account(conn, account["email"])
    return {"id": customer_id, "email": account["email"], "status": "closed"}
