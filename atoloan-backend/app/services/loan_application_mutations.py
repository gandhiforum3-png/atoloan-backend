"""
Persist findback results: upsert user record, insert loan application row.
"""
import logging
from typing import Optional

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.loan_application_table import loan_applications_table
from app.models.user_table import user_table

logger = logging.getLogger(__name__)


async def save_findback_result(
    conn: AsyncConnection,
    *,
    # user fields
    email: str,
    first_name: str,
    last_name: str,
    address: Optional[str],
    city: Optional[str],
    state: Optional[str],
    zipcode: Optional[str],
    phone_number: Optional[str],
    # loan inputs
    down_payment: Optional[float],
    credit_score: Optional[int],
    # 700Credit prequal result dict (from PrequalResult.to_dict())
    prequal: dict,
    # best bank offer dict (from find_best_bank) or None
    best_bank: Optional[dict],
) -> int:
    """
    Upsert the user record then insert a new loan_applications row.

    Returns the new loan application id.
    """
    # --- 1. Upsert user ---
    await conn.execute(
        text("""
            INSERT INTO users (email, first_name, last_name, address, city, state, zipcode, phone_number)
            VALUES (:email, :first_name, :last_name, :address, :city, :state, :zipcode, :phone_number)
            ON CONFLICT (email) DO UPDATE SET
                first_name   = EXCLUDED.first_name,
                last_name    = EXCLUDED.last_name,
                address      = COALESCE(EXCLUDED.address, users.address),
                city         = COALESCE(EXCLUDED.city, users.city),
                state        = COALESCE(EXCLUDED.state, users.state),
                zipcode      = COALESCE(EXCLUDED.zipcode, users.zipcode),
                phone_number = COALESCE(EXCLUDED.phone_number, users.phone_number),
                last_modified_at = NOW()
        """),
        {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "address": address,
            "city": city,
            "state": state,
            "zipcode": zipcode,
            "phone_number": phone_number,
        },
    )
    logger.info("Upserted user: %s", email)

    # --- 2. Insert loan application ---
    # Strip raw_xml from prequal before storing as JSONB
    prequal_raw = {k: v for k, v in prequal.items() if k != "raw_xml"}

    result = await conn.execute(
        insert(loan_applications_table).values(
            email=email,
            first_name=first_name,
            last_name=last_name,
            address=address,
            city=city,
            state=state,
            zipcode=zipcode,
            phone_number=phone_number,
            down_payment=down_payment,
            credit_score=credit_score,
            prequal_result_code=prequal.get("result_code"),
            prequal_result_description=prequal.get("result_description"),
            prequal_score=prequal.get("score"),
            prequal_tier=prequal.get("tier"),
            prequal_score_range=prequal.get("score_range"),
            prequal_transid=prequal.get("transid"),
            prequal_raw=prequal_raw,
            bank_id=best_bank.get("bank_id") if best_bank else None,
            bank_name=best_bank.get("bank_name") if best_bank else None,
            interest_rate=best_bank.get("interest_rate") if best_bank else None,
            program_name=best_bank.get("program_name") if best_bank else None,
            tier_name=best_bank.get("tier_name") if best_bank else None,
            term_in_months=best_bank.get("term_in_months") if best_bank else None,
            min_loan_amount=best_bank.get("min_loan_amount") if best_bank else None,
            max_loan_amount=best_bank.get("max_loan_amount") if best_bank else None,
        ).returning(loan_applications_table.c.id)
    )
    app_id = result.scalar_one()
    logger.info("Inserted loan application id=%d for user %s", app_id, email)
    return app_id
