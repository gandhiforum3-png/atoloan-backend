"""
Read-side queries for loan_applications — used by dealer-hub-backend to show
a dealer their own submitted applications ("application status").
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.loan_application_table import loan_applications_table


async def get_applications_for_dealer(
    conn: AsyncConnection, dealer_id: str, limit: int = 200
) -> list[dict]:
    """
    One row per unique applicant (by email) — their most recent submission —
    most-recent-first. A dealer's own re-submits (e.g. a double-click, or
    re-checking after adding a bank) create a new loan_applications row
    each time by design (append-only audit trail), but this status view
    should show current status per applicant, not every historical attempt.
    Excludes prequal_raw (verbose XML).
    """
    columns = ", ".join(f'"{c.name}"' for c in loan_applications_table.c if c.name != "prequal_raw")
    result = await conn.execute(
        text(f"""
            SELECT * FROM (
                SELECT DISTINCT ON (email) {columns}
                FROM loan_applications
                WHERE dealer_id = :dealer_id
                ORDER BY email, created_at DESC
            ) latest_per_applicant
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"dealer_id": dealer_id, "limit": limit},
    )
    return [dict(row._mapping) for row in result.fetchall()]
