"""
Customer account data shared by the customer portal (/me) and the admin API
(/customers): the editable profile, an account's own applications, and closing
an account.
"""
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.services.customer_auth import PROFILE_COLUMNS, normalize_email


class ProfileUpdate(BaseModel):
    """Contact fields a customer (or an admin, for them) may change. Email is the
    sign-in identity and is not editable; unknown fields are ignored."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    phone_number: str | None = Field(None, pattern=r"^\d{10}$")
    address: str | None = Field(None, min_length=1, max_length=255)
    city: str | None = Field(None, min_length=1, max_length=100)
    state: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    zipcode: str | None = Field(None, pattern=r"^\d{5}$")


_PROFILE_SELECT = ", ".join(PROFILE_COLUMNS)


async def get_profile(conn: AsyncConnection, email: str) -> dict | None:
    row = (
        await conn.execute(text(f"SELECT {_PROFILE_SELECT} FROM users WHERE email = :e"), {"e": normalize_email(email)})
    ).mappings().first()
    return dict(row) if row else None


async def update_profile(conn: AsyncConnection, email: str, changes: ProfileUpdate) -> tuple[dict, dict] | None:
    """(before, after) profile, or None when there's no such account."""
    before = await get_profile(conn, email)
    if before is None:
        return None
    fields = changes.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        return before, before
    # Column names come from the model's fixed field list, never from the client
    assignments = ", ".join(f"{name} = :{name}" for name in fields)
    after = (
        await conn.execute(
            text(f"UPDATE users SET {assignments}, last_modified_at = NOW() WHERE email = :e RETURNING {_PROFILE_SELECT}"),
            {**fields, "e": normalize_email(email)},
        )
    ).mappings().one()
    return before, dict(after)


async def list_customer_applications(conn: AsyncConnection, email: str) -> list[dict]:
    """The account's own pulls (run while signed in), newest first. Offer and
    document status only — never the credit score or tier."""
    rows = (
        await conn.execute(
            text("""
                SELECT id, created_at, bank_id, bank_name, interest_rate, term_in_months, program_name,
                       drivers_license_key IS NOT NULL AS has_drivers_license,
                       paycheck_key IS NOT NULL AS has_paycheck
                FROM loan_applications
                WHERE customer_email = :e
                ORDER BY created_at DESC, id DESC
                LIMIT 100
            """),
            {"e": normalize_email(email)},
        )
    ).mappings().all()
    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "status": "matched" if row["bank_id"] is not None else "in_review",
            "bank_name": row["bank_name"],
            "interest_rate": row["interest_rate"],
            "term_in_months": row["term_in_months"],
            "program_name": row["program_name"],
            "documents": {"drivers_license": row["has_drivers_license"], "paycheck": row["has_paycheck"]},
        }
        for row in rows
    ]


async def close_account(conn: AsyncConnection, email: str) -> bool:
    """Delete the account: profile, sessions (cascade) and any pending code.
    Applications and credit-pull records stay — they are the FCRA/ECOA audit trail."""
    email = normalize_email(email)
    await conn.execute(text("DELETE FROM customer_login_codes WHERE email = :e"), {"e": email})
    deleted = await conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
    return deleted.rowcount > 0
