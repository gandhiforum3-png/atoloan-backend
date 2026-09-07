"""
700Credit findback / pre-qualification and zipcode validation endpoints.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.core.dependencies import get_conn
from app.db import get_engine
from app.integrations.dealer_hub_client import DealerHubUnavailableError, get_dealer_bank_ids
from app.integrations.seven_hundred import SevenHundredCreditClient
from app.services.application_email import send_application_summary_email
from app.services.bank_finder import find_matching_banks, get_term_options_for_offer
from app.services.loan_application_mutations import save_findback_result

logger = logging.getLogger(__name__)

router = APIRouter(tags=["findback"])


@router.post("/findback")
async def findback(request: Request, background_tasks: BackgroundTasks) -> dict:
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
    vehicle_price = _resolve_vehicle_price(original_payload)
    vehicle_type = _resolve_vehicle_type(original_payload)
    vehicle_mileage = _resolve_vehicle_mileage(original_payload)
    credit_score = result.score
    zipcode = payload.get("zip_code")

    # loan_amount is what actually gets financed — vehicle price minus down
    # payment — NOT the down payment itself. Loan program tiers (min/max
    # loan amount) are matched against this, not against down_payment.
    loan_amount = None
    if vehicle_price and vehicle_price > (down_payment or 0):
        loan_amount = vehicle_price - (down_payment or 0)

    # DTI ratio (existing monthly debt / monthly income, as a percentage) —
    # optional. Only computable when 700Credit returned trade line data
    # (result.monthly_debt) and the applicant provided monthly income.
    monthly_income = _resolve_monthly_income(original_payload)
    dti_ratio = None
    if result.monthly_debt is not None and monthly_income:
        dti_ratio = (result.monthly_debt / monthly_income) * 100

    # LTV ratio (loan_amount / vehicle_price, as a percentage) — used to apply
    # bank "ltv_threshold" rate adjustments. Only computable when we have
    # both a resolved loan_amount and vehicle_price (same guard as above).
    ltv_ratio = None
    if loan_amount and vehicle_price:
        ltv_ratio = (loan_amount / vehicle_price) * 100

    # Dealer-scoped search: if a dealer_id was supplied, restrict bank
    # matching to that dealer's mapped network (dealer-hub-backend owns
    # this mapping). No dealer_id means search every eligible bank, same
    # as before this parameter existed. If dealer-hub-backend itself is
    # unreachable, fall back to searching all banks rather than failing
    # the request — same best-effort philosophy as the rest of this step.
    dealer_id = original_payload.get("dealer_id")
    bank_ids = None
    if dealer_id:
        try:
            bank_ids = await get_dealer_bank_ids(str(dealer_id))
            logger.info("Dealer %s network: %d bank(s)", dealer_id, len(bank_ids))
        except DealerHubUnavailableError:
            logger.exception(
                "Dealer hub unavailable — searching all banks instead of dealer %s's network", dealer_id
            )
            bank_ids = None

    matched_banks: list = []
    best_offer = None
    if loan_amount and credit_score and zipcode:
        try:
            async with get_engine().begin() as conn:
                matched_banks = await find_matching_banks(
                    conn,
                    dti_ratio=dti_ratio,
                    zipcode=str(zipcode),
                    loan_amount=float(loan_amount),
                    credit_score=int(credit_score),
                    ltv_ratio=ltv_ratio,
                    vehicle_type=vehicle_type,
                    vehicle_mileage=vehicle_mileage,
                    bank_ids=bank_ids,
                )
                best_offer = matched_banks[0] if matched_banks else None
                if best_offer:
                    try:
                        rate_delta = best_offer["effective_rate"] - best_offer["rate_value"]
                        best_offer["term_options"] = await get_term_options_for_offer(
                            conn,
                            bank_id=best_offer["bank_id"],
                            program_name=best_offer["program_name"],
                            tier_name=best_offer["tier_name"],
                            credit_score=int(credit_score),
                            loan_amount=float(loan_amount),
                            rate_delta=rate_delta,
                        )
                    except Exception:
                        logger.exception("Failed to load term options — best_bank still returned without them")
            if matched_banks:
                response["matched_banks"] = matched_banks
                response["best_bank"] = best_offer
                logger.info(
                    "Bank finder: %d matching bank(s), best=%s at %s",
                    len(matched_banks), best_offer["bank_name"], best_offer["interest_rate"],
                )
            else:
                logger.warning("Bank finder: no eligible banks for zipcode=%s", zipcode)
        except Exception:
            logger.exception("Bank finder failed — skipping")
    else:
        missing_params = [
            p for p, v in [("loan_amount", loan_amount), ("credit_score", credit_score), ("zipcode", zipcode)]
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
                dealer_id=str(dealer_id) if dealer_id else None,
                matched_banks=matched_banks or None,
            )
        response["application_id"] = app_id
        logger.info("Saved loan application id=%d for %s", app_id, payload["email"])
    except Exception:
        logger.exception("Failed to save loan application — continuing")

    background_tasks.add_task(
        _send_summary_email_task,
        to_address=payload["email"],
        first_name=payload["first_name"],
        credit_score=int(credit_score) if credit_score else None,
        best_offer=best_offer,
    )

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

def _send_summary_email_task(
    *, to_address: str, first_name: str, credit_score: int | None, best_offer: dict | None
) -> None:
    """Runs as a FastAPI background task, after the response is sent — a
    slow or failing email send must never delay or fail /findback itself."""
    try:
        send_application_summary_email(
            to_address=to_address,
            first_name=first_name,
            credit_score=credit_score,
            best_offer=best_offer,
        )
    except Exception:
        logger.exception("Failed to send application summary email to %s", to_address)


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


def _resolve_vehicle_price(original_payload: dict) -> float | None:
    """Extract a numeric vehicle price from the raw request payload."""
    answers = original_payload.get("answers", {})
    price = answers.get("vehicle-price")
    if price:
        try:
            s = str(price)
            if "-" in s:
                lo, hi = s.split("-", 1)
                return (float(lo.strip()) + float(hi.strip())) / 2
            return float(s)
        except (ValueError, IndexError):
            logger.warning("Could not parse vehicle-price: %s", price)

    return None


def _resolve_vehicle_type(original_payload: dict) -> str | None:
    """Extract the vehicle type from the raw request payload. Must match
    one of the literal values loan_program_items.vehicle_type is stored
    as (see app/models/rate_sheet.py VehicleType) — anything else is
    treated as unset rather than guessed at."""
    answers = original_payload.get("answers", {})
    value = answers.get("vehicle-type")
    if value in ("New", "Used", "Certified Pre-Owned"):
        return value
    if value:
        logger.warning("Unrecognized vehicle-type: %s", value)
    return None


def _resolve_vehicle_mileage(original_payload: dict) -> int | None:
    """Extract a numeric vehicle mileage from the raw request payload."""
    answers = original_payload.get("answers", {})
    mileage = answers.get("vehicle-mileage")
    if mileage:
        try:
            return int(float(str(mileage)))
        except (ValueError, TypeError):
            logger.warning("Could not parse vehicle-mileage: %s", mileage)

    return None


def _resolve_monthly_income(original_payload: dict) -> float | None:
    """Extract a numeric monthly income from the raw request payload."""
    answers = original_payload.get("answers", {})
    income = answers.get("monthly-income")
    if income:
        try:
            return float(str(income))
        except ValueError:
            logger.warning("Could not parse monthly-income: %s", income)

    return None
