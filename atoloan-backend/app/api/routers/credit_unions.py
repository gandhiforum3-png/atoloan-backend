"""
Credit union CRUD endpoints.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dependencies import get_conn
from app.core.security import require_service_token
from app.models.rate_sheet import CreditUnionRateSheet
from app.services.credit_unions import (
    delete_credit_union_and_related,
    get_all_credit_unions,
    get_bank_info,
    get_loan_programs,
    get_rate_policy,
    upsert_bank_info,
    upsert_loan_program_items,
    upsert_rate_policy_items,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/credit-unions",
    tags=["credit-unions"],
    dependencies=[Depends(require_service_token)],
)


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
        raise HTTPException(status_code=500, detail="failed to delete credit union") from exc

    return {
        "status": "success",
        "message": f"Credit union '{deleted['bank_name']}' deleted successfully",
        "deleted": deleted,
    }


@router.post("/{bank_id}/approval")
async def set_approval(bank_id: int, request: Request, conn: AsyncConnection = Depends(get_conn)) -> dict:
    """Approve (or send back to pending) a lender. Only approved lenders are
    offered to customers by the bank finder."""
    payload = await request.json()
    status = payload.get("status") if isinstance(payload, dict) else None
    if status not in ("approved", "pending"):
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'pending'")
    row = (
        await conn.execute(
            text("UPDATE bank_info SET approval_status = :status WHERE bank_id = :bank_id RETURNING name"),
            {"status": status, "bank_id": bank_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Credit union {bank_id} not found")
    logger.info("bank_id=%s approval_status -> %s", bank_id, status)
    return {"bank_id": bank_id, "name": row[0], "approval_status": status}


# Standalone /update endpoint (upsert full rate sheet)
update_router = APIRouter(tags=["credit-unions"], dependencies=[Depends(require_service_token)])


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
    try:
        sheet = CreditUnionRateSheet.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="payload is not a valid rate sheet") from exc
    # Only fields the schema knows about reach the database
    payload = sheet.model_dump(mode="json")
    bank_name = (payload.get("credit_union_info") or {}).get("name") or "Unknown"
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
        raise HTTPException(status_code=500, detail="database upsert failed") from exc
