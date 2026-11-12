"""
Read-only loan application listings for dealer-hub-backend: a dealer's own
applications, and the all-dealers view for atoloan admins.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dependencies import get_conn
from app.core.security import require_service_token
from app.models.loan_application_table import loan_applications_table as la

router = APIRouter(tags=["loan-applications"], dependencies=[Depends(require_service_token)])

# What a reviewer needs — never the raw 700Credit payload, upload token hash or client IP.
_COLUMNS = [
    la.c.id,
    la.c.dealer_id,
    la.c.created_at,
    la.c.consent_at,
    la.c.first_name,
    la.c.last_name,
    la.c.email,
    la.c.phone_number,
    la.c.address,
    la.c.city,
    la.c.state,
    la.c.zipcode,
    la.c.down_payment,
    la.c.prequal_result_code,
    la.c.prequal_result_description,
    la.c.prequal_score,
    la.c.prequal_tier,
    la.c.bank_id,
    la.c.bank_name,
    la.c.interest_rate,
    la.c.program_name,
    la.c.tier_name,
    la.c.term_in_months,
]


def _filters(dealer_id: str | None, q: str | None = None) -> list:
    where = [la.c.dealer_id == dealer_id] if dealer_id else []
    if q and q.strip():
        # Customer lookup: any part of name, email or phone. autoescape so a
        # '%' or '_' typed by the admin is matched literally, not as a wildcard.
        term = q.strip()
        where.append(
            or_(
                (la.c.first_name + " " + la.c.last_name).icontains(term, autoescape=True),
                la.c.email.icontains(term, autoescape=True),
                la.c.phone_number.icontains(term, autoescape=True),
            )
        )
    return where


async def _list(conn: AsyncConnection, dealer_id: str | None, limit: int, offset: int, q: str | None = None) -> dict:
    where = _filters(dealer_id, q)
    rows = (
        await conn.execute(
            select(*_COLUMNS).where(*where).order_by(la.c.created_at.desc(), la.c.id.desc()).limit(limit).offset(offset)
        )
    ).mappings().all()
    total = await conn.scalar(select(func.count()).select_from(la).where(*where))
    return {"applications": [dict(row) for row in rows], "total": total}


async def _summary(conn: AsyncConnection, dealer_id: str | None, q: str | None = None) -> dict:
    where = _filters(dealer_id, q)
    row = (
        await conn.execute(
            select(
                func.count().label("total"),
                func.count().filter(la.c.bank_id.is_not(None)).label("matched"),
                func.count().filter(la.c.created_at > func.now() - text("INTERVAL '7 days'")).label("last_7_days"),
            ).where(*where)
        )
    ).mappings().one()
    return {**row, "unmatched": row["total"] - row["matched"]}


@router.get("/dealers/{dealer_id}/loan-applications/summary")
async def dealer_applications_summary(dealer_id: str, conn: AsyncConnection = Depends(get_conn)) -> dict:
    """Counts over ALL of a dealer's applications (not just one page)."""
    return await _summary(conn, dealer_id)


@router.get("/loan-applications/summary")
async def all_applications_summary(
    dealer_id: str | None = None,
    q: str | None = Query(None, max_length=100),
    conn: AsyncConnection = Depends(get_conn),
) -> dict:
    return await _summary(conn, dealer_id, q)


@router.get("/dealers/{dealer_id}/loan-applications")
async def list_dealer_applications(
    dealer_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: AsyncConnection = Depends(get_conn),
) -> dict:
    """One dealer's applications (soft pulls run from their portal)."""
    return await _list(conn, dealer_id, limit, offset)


@router.get("/loan-applications")
async def list_all_applications(
    dealer_id: str | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: AsyncConnection = Depends(get_conn),
) -> dict:
    """Every application, newest first — admin view. Optional dealer filter and
    customer search (name, email or phone)."""
    return await _list(conn, dealer_id, limit, offset, q)
