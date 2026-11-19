"""
Read-only loan application listing, scoped to one dealer at a time.

Unauthenticated here by design — same trust boundary as /credit-unions and
dealer-hub-backend's own /internal endpoints: dealer-hub-backend is the
public-facing auth gateway and is trusted to only ever ask for the
dealer_id of whichever dealer is actually logged in on its side.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dependencies import get_conn
from app.services.loan_application_queries import (
    get_applications_for_dealer,
    get_summary_for_dealer,
)

router = APIRouter(tags=["loan-applications"])


@router.get("/dealers/{dealer_id}/loan-applications")
async def list_dealer_loan_applications(
    dealer_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: AsyncConnection = Depends(get_conn),
) -> dict:
    page = await get_applications_for_dealer(conn, dealer_id, limit=limit, offset=offset)
    return {"dealer_id": dealer_id, **page}


@router.get("/dealers/{dealer_id}/loan-applications/summary")
async def dealer_loan_applications_summary(
    dealer_id: str, conn: AsyncConnection = Depends(get_conn)
) -> dict:
    return await get_summary_for_dealer(conn, dealer_id)
