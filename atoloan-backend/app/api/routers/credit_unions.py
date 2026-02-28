"""
Credit union CRUD endpoints.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dependencies import get_conn
from app.services.credit_union_deletion import delete_credit_union_and_related
from app.services.credit_union_mutations import (
    upsert_bank_info,
    upsert_loan_program_items,
    upsert_rate_policy_items,
)
from app.services.credit_union_retrieval import (
    get_all_credit_unions,
    get_bank_info,
    get_loan_programs,
    get_rate_policy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credit-unions", tags=["credit-unions"])


@router.get("")
async def list_credit_unions(conn: AsyncConnection = Depends(get_conn)) -> dict:
    """Return all credit unions (id + name)."""
    credit_unions = await get_all_credit_unions(conn)
    return {"status": "success", "credit_unions": credit_unions, "count": len(credit_unions)}


@router.get("/{bank_id}/ratesheet")
async def get_ratesheet(bank_id: int, conn: AsyncConnection = Depends(get_conn)) -> dict:
    """Return a complete rate sheet for a single credit union."""
    bank_info_data = await get_bank_info(conn, bank_id)
    if not bank_info_data:
        raise HTTPException(status_code=404, detail=f"Credit union {bank_id} not found")

    rate_policy_data = await get_rate_policy(conn, bank_id)
    loan_programs_data = await get_loan_programs(conn, bank_id)

    return {
        "bank_id": bank_id,
        "credit_union_info": bank_info_data["credit_union_info"],
        "rate_policy": rate_policy_data,
        "loan_programs": loan_programs_data,
        "guidelines": bank_info_data["guidelines"],
        "special_programs": bank_info_data["special_programs"],
        "participation_and_funding": bank_info_data["participation_and_funding"],
        "additional_details": bank_info_data["additional_details"],
    }


@router.delete("/{bank_id}")
async def delete_credit_union(bank_id: int, conn: AsyncConnection = Depends(get_conn)) -> dict:
    """Delete a credit union and all its related data."""
    try:
        deleted = await delete_credit_union_and_related(conn, bank_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to delete credit union %s", bank_id)
        raise HTTPException(status_code=500, detail=f"Failed to delete credit union: {exc}") from exc

    return {
        "status": "success",
        "message": f"Credit union '{deleted['bank_name']}' deleted successfully",
        "deleted": deleted,
    }


# Standalone /update endpoint (upsert full rate sheet)
update_router = APIRouter(tags=["credit-unions"])


@update_router.post("/update")
async def update_rate_sheet(
    request: Request,
    conn: AsyncConnection = Depends(get_conn),
) -> dict:
    """
    Upsert a full rate sheet payload (credit_union_info, rate_policy,
    loan_programs, guidelines, special_programs, participation_and_funding,
    additional_details) into the database.
    """
    payload = await request.json()
    bank_name = (payload.get("credit_union_info") or {}).get("name", "Unknown")
    logger.info("update endpoint called for bank: %s", bank_name)

    try:
        bank_id = await upsert_bank_info(conn, payload)
        rate_policy_count = await upsert_rate_policy_items(conn, bank_id, payload)
        loan_program_count = await upsert_loan_program_items(conn, bank_id, payload)

        logger.info(
            "upserted bank_id=%s rate_policy_items=%s loan_program_items=%s",
            bank_id, rate_policy_count, loan_program_count,
        )
        return {
            "status": "success",
            "bank_id": bank_id,
            "rate_policy_items_count": rate_policy_count,
            "loan_program_items_count": loan_program_count,
        }
    except Exception as exc:
        logger.exception("Failed to upsert rate sheet for %s", bank_name)
        raise HTTPException(status_code=500, detail=f"Database upsert failed: {exc}") from exc
