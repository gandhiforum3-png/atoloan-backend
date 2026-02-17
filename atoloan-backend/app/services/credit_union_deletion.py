"""
Credit Union Deletion Service
Handles all PostgreSQL DELETE operations for credit unions and related data.
"""
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def delete_credit_union_and_related(conn: AsyncConnection, bank_id: int) -> dict:
    """
    Delete a credit union and all its related data.

    Deletes from:
    - loan_program_items (all programs, tiers, terms)
    - rate_policy_items (discounts, adjustments, fees)
    - bank_info (credit union information)

    Args:
        conn: Database connection
        bank_id: The bank ID to delete

    Returns:
        Dict with bank_name and counts of deleted records

    Raises:
        ValueError: If credit union not found
    """
    # First check if bank exists
    check_query = text("SELECT name FROM bank_info WHERE bank_id = :bank_id")
    result = await conn.execute(check_query, {"bank_id": bank_id})
    bank_row = result.fetchone()

    if not bank_row:
        raise ValueError(f"Credit union with ID {bank_id} not found")

    bank_name = bank_row[0]

    # Delete loan_program_items
    loan_delete_query = text("DELETE FROM loan_program_items WHERE bank_id = :bank_id")
    loan_result = await conn.execute(loan_delete_query, {"bank_id": bank_id})
    loan_count = loan_result.rowcount

    # Delete rate_policy_items
    rate_delete_query = text("DELETE FROM rate_policy_items WHERE bank_id = :bank_id")
    rate_result = await conn.execute(rate_delete_query, {"bank_id": bank_id})
    rate_count = rate_result.rowcount

    # Delete bank_info
    bank_delete_query = text("DELETE FROM bank_info WHERE bank_id = :bank_id")
    await conn.execute(bank_delete_query, {"bank_id": bank_id})

    logging.info(f"[DELETE] Successfully deleted credit union '{bank_name}' (ID: {bank_id})")

    return {
        "bank_id": bank_id,
        "bank_name": bank_name,
        "loan_program_items": loan_count,
        "rate_policy_items": rate_count
    }
