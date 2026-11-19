"""
Read-side queries for loan_applications — used by dealer-hub-backend to show
a dealer their own submitted applications ("application status").
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.loan_application_table import loan_applications_table

# One row per applicant (their latest submission). A dealer's re-runs append
# a new row by design (audit trail), but status views show current state per
# applicant, not every historical attempt.
_LATEST_PER_APPLICANT = """
    SELECT DISTINCT ON (email) {columns}
    FROM loan_applications
    WHERE dealer_id = :dealer_id
    ORDER BY email, created_at DESC
"""


def _columns() -> str:
    return ", ".join(f'"{c.name}"' for c in loan_applications_table.c if c.name != "prequal_raw")


async def get_applications_for_dealer(
    conn: AsyncConnection, dealer_id: str, limit: int = 50, offset: int = 0
) -> dict:
    """A page of the dealer's applicants, newest first, plus the full count
    so the caller can show "showing N of TOTAL" and drive Load More."""
    latest = _LATEST_PER_APPLICANT.format(columns=_columns())

    rows = (
        await conn.execute(
            text(f"""
                SELECT * FROM ({latest}) latest_per_applicant
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"dealer_id": dealer_id, "limit": limit, "offset": offset},
        )
    ).fetchall()

    total = await conn.scalar(
        text(f"SELECT COUNT(*) FROM ({_LATEST_PER_APPLICANT.format(columns='email')}) t"),
        {"dealer_id": dealer_id},
    )

    return {"applications": [dict(r._mapping) for r in rows], "total": int(total or 0)}


async def get_summary_for_dealer(conn: AsyncConnection, dealer_id: str) -> dict:
    """Counts across all of the dealer's applicants — matched meaning the
    bank finder landed on an offer (bank_id set)."""
    latest = _LATEST_PER_APPLICANT.format(columns="email, bank_id, created_at")

    row = (
        await conn.execute(
            text(f"""
                SELECT
                    COUNT(*)                                                        AS total,
                    COUNT(bank_id)                                                  AS matched,
                    COUNT(*) FILTER (WHERE bank_id IS NULL)                         AS unmatched,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS last_7_days
                FROM ({latest}) latest_per_applicant
            """),
            {"dealer_id": dealer_id},
        )
    ).fetchone()

    m = row._mapping
    return {k: int(m[k] or 0) for k in ("total", "matched", "unmatched", "last_7_days")}
