"""
Persist findback results: insert user record if new, insert loan application row.
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.loan_application_table import loan_applications_table
from app.models.user_table import user_table
from app.services.customer_auth import normalize_email

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
    upload_token_hash: Optional[str] = None,
    dealer_id: Optional[str] = None,
    consent_at: Optional[datetime] = None,
    client_ip: Optional[str] = None,
    customer_email: Optional[str] = None,
) -> int:
    """
    Insert the user record if new, then insert a new loan_applications row.

    Returns the new loan application id.
    """
    # One spelling per address, whoever typed it (customer, dealer, guest)
    email = normalize_email(email)
    # --- 1. Insert user if new ---
    # Unverified (dealer/service) pulls never rewrite an existing record. A pull
    # from the customer's own verified session fills profile fields that are
    # still empty — so their next application is pre-filled — and never
    # overwrites what they've already set. Each application keeps its own snapshot.
    on_conflict = (
        """DO UPDATE SET
                first_name   = CASE WHEN users.first_name = '' THEN EXCLUDED.first_name ELSE users.first_name END,
                last_name    = CASE WHEN users.last_name = '' THEN EXCLUDED.last_name ELSE users.last_name END,
                address      = COALESCE(users.address, EXCLUDED.address),
                city         = COALESCE(users.city, EXCLUDED.city),
                state        = COALESCE(users.state, EXCLUDED.state),
                zipcode      = COALESCE(users.zipcode, EXCLUDED.zipcode),
                phone_number = COALESCE(users.phone_number, EXCLUDED.phone_number),
                last_modified_at = NOW()"""
        if customer_email
        else "DO NOTHING"
    )
    await conn.execute(
        text(f"""
            INSERT INTO users (email, first_name, last_name, address, city, state, zipcode, phone_number)
            VALUES (:email, :first_name, :last_name, :address, :city, :state, :zipcode, :phone_number)
            ON CONFLICT (email) {on_conflict}
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

    # --- 2. Insert loan application ---
    # The raw report, its access token and the report URL are the consumer's
    # full credit file — the summary columns are all we keep.
    prequal_raw = {k: v for k, v in prequal.items() if k not in ("raw_xml", "token", "iframe_url")}

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
            upload_token_hash=upload_token_hash,
            dealer_id=dealer_id,
            consent_at=consent_at,
            client_ip=client_ip,
            customer_email=customer_email,
        ).returning(loan_applications_table.c.id)
    )
    app_id = result.scalar_one()
    logger.info("Inserted loan application id=%d", app_id)
    return app_id
