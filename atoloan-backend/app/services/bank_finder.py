"""
Bank Finder Algorithm
Finds the best bank/credit union based on user's location, down payment, and credit score.
"""
import logging
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def find_best_bank(
    conn: AsyncConnection,
    zipcode: str,
    down_payment: float,
    credit_score: int
) -> Optional[dict]:
    """
    Find the best bank with the lowest interest rate for the given criteria.

    Args:
        conn: Database connection
        zipcode: User's zipcode
        down_payment: User's down payment amount
        credit_score: User's credit score

    Returns:
        Dict with best bank info and rate, or None if no eligible bank found
        {
            "bank_id": int,
            "bank_name": str,
            "interest_rate": str,
            "program_name": str,
            "tier_name": str,
            "term_in_months": int,
            "min_loan_amount": int,
            "max_loan_amount": int
        }
    """
    logging.info(f"[BANK FINDER] Starting search for zipcode={zipcode}, down_payment={down_payment}, credit_score={credit_score}")

    # Step 1: Get user's county from zipcode
    user_county = await _get_county_from_zipcode(conn, zipcode)
    if not user_county:
        logging.warning(f"[BANK FINDER] Zipcode {zipcode} not found in database")
        return None

    logging.info(f"[BANK FINDER] User location: zipcode={zipcode}, county={user_county}")

    # Step 2: Find all eligible banks for this location
    eligible_banks = await _get_eligible_banks(conn, zipcode, user_county)
    if not eligible_banks:
        logging.warning(f"[BANK FINDER] No eligible banks found for zipcode {zipcode}")
        return None

    logging.info(f"[BANK FINDER] Found {len(eligible_banks)} eligible banks")

    # Step 3: Find best rate among eligible banks
    best_offer = await _find_best_rate(
        conn,
        eligible_banks,
        down_payment,
        credit_score
    )

    if best_offer:
        logging.info(
            f"[BANK FINDER] Best offer: {best_offer['bank_name']} "
            f"(rate={best_offer['interest_rate']}, "
            f"program={best_offer['program_name']}, "
            f"tier={best_offer['tier_name']})"
        )
    else:
        logging.warning(f"[BANK FINDER] No suitable offers found for credit_score={credit_score}, down_payment={down_payment}")

    return best_offer


async def _get_county_from_zipcode(conn: AsyncConnection, zipcode: str) -> Optional[str]:
    """
    Get county name from zipcode table.

    Args:
        conn: Database connection
        zipcode: User's zipcode

    Returns:
        County name or None if not found
    """
    query = text("""
        SELECT city FROM zipcode WHERE zipcode = :zipcode LIMIT 1
    """)

    result = await conn.execute(query, {"zipcode": str(zipcode)})
    row = result.fetchone()

    return row[0] if row else None


async def _get_eligible_banks(
    conn: AsyncConnection,
    zipcode: str,
    user_county: str
) -> list[dict]:
    """
    Get all banks eligible to provide loans in the user's location.

    A bank is eligible if:
    1. accept_out_region_loans is True (eligible for entire USA), OR
    2. accept_out_region_loans is False/NULL but out_region_list is empty/NULL (eligible for entire USA), OR
    3. User's county is in the bank's out_region_list

    Args:
        conn: Database connection
        zipcode: User's zipcode
        user_county: User's county name

    Returns:
        List of eligible bank records
    """
    query = text("""
        SELECT
            bank_id,
            name,
            accept_out_region_loans,
            out_region_list
        FROM bank_info
        WHERE
            -- Bank accepts out of region loans (entire USA)
            accept_out_region_loans = true
            OR
            -- No restrictions specified (entire USA)
            (out_region_list IS NULL OR out_region_list = '{}')
            OR
            -- User's county is in the eligible list
            :user_county = ANY(out_region_list)
        ORDER BY name
    """)

    result = await conn.execute(query, {"user_county": user_county})
    rows = result.fetchall()

    eligible_banks = []
    for row in rows:
        eligible_banks.append({
            "bank_id": row[0],
            "name": row[1],
            "accept_out_region_loans": row[2],
            "out_region_list": row[3]
        })

    return eligible_banks


async def _find_best_rate(
    conn: AsyncConnection,
    eligible_banks: list[dict],
    down_payment: float,
    credit_score: int
) -> Optional[dict]:
    """
    Find the best interest rate among eligible banks.

    Args:
        conn: Database connection
        eligible_banks: List of eligible bank records
        down_payment: User's down payment amount
        credit_score: User's credit score

    Returns:
        Best offer dict or None
    """
    best_offer = None
    best_rate = float('inf')

    for bank in eligible_banks:
        bank_id = bank["bank_id"]
        bank_name = bank["name"]

        # Query loan programs for this bank with matching credit score and loan amount
        query = text("""
            SELECT
                program_name,
                tier_name,
                term_in_months,
                min_loan_amount,
                max_loan_amount,
                rate,
                min_credit_score,
                max_credit_score
            FROM loan_program_items
            WHERE
                bank_id = :bank_id
                AND item_type = 'term'
                AND min_credit_score <= :credit_score
                AND max_credit_score >= :credit_score
                AND (min_loan_amount IS NULL OR min_loan_amount <= :down_payment)
                AND (max_loan_amount IS NULL OR max_loan_amount >= :down_payment)
                AND rate IS NOT NULL
            ORDER BY rate ASC
            LIMIT 1
        """)

        result = await conn.execute(query, {
            "bank_id": bank_id,
            "credit_score": credit_score,
            "down_payment": down_payment
        })

        row = result.fetchone()

        if row:
            # Extract rate percentage value (e.g., "5.25%" -> 5.25)
            rate_str = row[5]
            try:
                # Remove % sign and convert to float
                rate_value = float(rate_str.replace('%', '').strip()) if isinstance(rate_str, str) else float(rate_str)
            except (ValueError, AttributeError):
                logging.warning(f"[BANK FINDER] Invalid rate format for {bank_name}: {rate_str}")
                continue

            # Check if this is the best rate so far
            if rate_value < best_rate:
                best_rate = rate_value
                best_offer = {
                    "bank_id": bank_id,
                    "bank_name": bank_name,
                    "interest_rate": rate_str,
                    "program_name": row[0],
                    "tier_name": row[1],
                    "term_in_months": row[2],
                    "min_loan_amount": row[3],
                    "max_loan_amount": row[4],
                    "min_credit_score": row[6],
                    "max_credit_score": row[7]
                }

    return best_offer
