"""
700Credit findback / pre-qualification and zipcode validation endpoints.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.core.dependencies import get_conn
from app.db import get_engine
from app.integrations.seven_hundred import SevenHundredCreditClient
from app.services.bank_finder import find_best_bank
from app.services.loan_application_mutations import save_findback_result

logger = logging.getLogger(__name__)

router = APIRouter(tags=["findback"])


@router.post("/findback")
async def findback(request: Request) -> dict:
    """
    Submit a pre-qualification request to 700Credit then run the bank finder
    to return the best rate offer alongside the credit result.

    The bank finder step is best-effort: if parameters are missing or the DB
    is unavailable the endpoint still returns the 700Credit result.
    """
    payload = await request.json()
    logger.info("findback payload: %s", payload)

    original_payload = dict(payload) if isinstance(payload, dict) else {}

    # Support nested contactInfo shape sent by the frontend
    if isinstance(payload, dict) and isinstance(payload.get("contactInfo"), dict):
        contact = payload["contactInfo"]
        payload = {
            "first_name": contact.get("firstName"),
            "last_name": contact.get("lastName"),
            "email": contact.get("email"),
            "phone_number": contact.get("phone"),
            "address": contact.get("address"),
            "city": contact.get("city"),
            "state": contact.get("state"),
            "zip_code": contact.get("zip"),
            "bureau": payload.get("bureau"),
            "ssn": payload.get("ssn"),
            "app_modified": payload.get("app_modified"),
            "extra_fields": payload.get("extra_fields"),
        }

    required = ["first_name", "last_name", "address", "city", "state", "zip_code", "email"]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"missing required fields: {', '.join(missing)}",
        )

    try:
        s = get_settings()
        if not s.sevencredit_account or not s.sevencredit_password:
            raise ValueError("SEVENCREDIT_ACCOUNT and SEVENCREDIT_PASSWORD are required")
        client = SevenHundredCreditClient(
            account=s.sevencredit_account,
            password=s.sevencredit_password,
            environment=s.sevencredit_env,
            client_id=s.sevencredit_client_id or None,
            client_secret=s.sevencredit_client_secret or None,
        )
        result = client.send_prequalify(
            first_name=payload["first_name"],
            last_name=payload["last_name"],
            address=payload["address"],
            city=payload["city"],
            state=payload["state"],
            zip_code=payload["zip_code"],
            bureau=payload.get("bureau", "TU"),
            ssn=payload.get("ssn"),
            app_modified=bool(payload.get("app_modified", False)),
            extra_fields=payload.get("extra_fields"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("findback request failed")
        raise HTTPException(status_code=502, detail="findback request failed") from exc

    response: dict = {"prequal": result.to_dict()}
    logger.info("findback 700Credit response received")

    # --- Bank Finder (best-effort, does not fail the request if unavailable) ---
    down_payment = _resolve_down_payment(original_payload)
    credit_score = 740  # placeholder until 700Credit returns an actual score
    zipcode = payload.get("zip_code")

    best_offer = None
    if down_payment and credit_score and zipcode:
        try:
            async with get_engine().begin() as conn:
                best_offer = await find_best_bank(
                    conn,
                    zipcode=str(zipcode),
                    down_payment=float(down_payment),
                    credit_score=int(credit_score),
                )
            if best_offer:
                response["best_bank"] = best_offer
                logger.info(
                    "Bank finder: %s at %s",
                    best_offer["bank_name"], best_offer["interest_rate"],
                )
            else:
                logger.warning("Bank finder: no eligible banks for zipcode=%s", zipcode)
        except Exception:
            logger.exception("Bank finder failed — skipping")
    else:
        missing_params = [
            p for p, v in [("down_payment", down_payment), ("credit_score", credit_score), ("zipcode", zipcode)]
            if not v
        ]
        logger.warning("Bank finder skipped — missing: %s", ", ".join(missing_params))

    # --- Persist user + loan application ---
    try:
        async with get_engine().begin() as conn:
            app_id = await save_findback_result(
                conn,
                email=payload["email"],
                first_name=payload["first_name"],
                last_name=payload["last_name"],
                address=payload.get("address"),
                city=payload.get("city"),
                state=payload.get("state"),
                zipcode=zipcode,
                phone_number=payload.get("phone_number"),
                down_payment=float(down_payment) if down_payment else None,
                credit_score=int(credit_score) if credit_score else None,
                prequal=result.to_dict(),
                best_bank=best_offer,
            )
        response["application_id"] = app_id
        logger.info("Saved loan application id=%d for %s", app_id, payload["email"])
    except Exception:
        logger.exception("Failed to save loan application — continuing")

    return response


@router.post("/validate-zipcode")
async def validate_zipcode(
    request: Request,
    conn: AsyncConnection = Depends(get_conn),
) -> dict:
    payload = await request.json()
    zipcode = payload.get("zipcode") if isinstance(payload, dict) else None
    if not zipcode:
        raise HTTPException(status_code=400, detail="zipcode is required")

    result = await conn.execute(
        text("SELECT city FROM zipcode WHERE zipcode = :zipcode LIMIT 1"),
        {"zipcode": str(zipcode)},
    )
    row = result.first()
    return {"zipcode": str(zipcode), "valid": row is not None, "city": row[0] if row else None}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _resolve_down_payment(original_payload: dict) -> float | None:
    """Extract a numeric down payment from the raw request payload."""
    value = original_payload.get("otherDownPayment")
    if value:
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning("Invalid otherDownPayment: %s", value)

    answers = original_payload.get("answers", {})
    dp_range = answers.get("down-payment")
    if dp_range:
        try:
            s = str(dp_range)
            if "-" in s:
                lo, hi = s.split("-", 1)
                return (float(lo.strip()) + float(hi.strip())) / 2
            return float(s)
        except (ValueError, IndexError):
            logger.warning("Could not parse down-payment range: %s", dp_range)

    return None
