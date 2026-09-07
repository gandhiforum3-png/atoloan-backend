"""
Read-only loan application listing, scoped to one dealer at a time.

Unauthenticated here by design — same trust boundary as /credit-unions and
dealer-hub-backend's own /internal endpoints: dealer-hub-backend is the
public-facing auth gateway and is trusted to only ever ask for the
dealer_id of whichever dealer is actually logged in on its side.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dependencies import get_conn
from app.services.loan_application_queries import get_applications_for_dealer

router = APIRouter(tags=["loan-applications"])


@router.get("/dealers/{dealer_id}/loan-applications")
async def list_dealer_loan_applications(
    dealer_id: str, conn: AsyncConnection = Depends(get_conn)
) -> dict:
    applications = await get_applications_for_dealer(conn, dealer_id)
    return {"dealer_id": dealer_id, "applications": applications, "count": len(applications)}
