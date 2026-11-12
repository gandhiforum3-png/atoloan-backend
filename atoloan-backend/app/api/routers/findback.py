"""
700Credit findback / pre-qualification and zipcode validation endpoints.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.captcha import client_ip as _client_ip
from app.core.config import get_settings
from app.core.customer_session import optional_customer
from app.core.dependencies import get_conn
from app.core.security import is_service_caller
from app.db import get_engine
from app.integrations.dealer_hub import get_dealer_bank_ids
from app.integrations.seven_hundred import SevenHundredCreditClient
from app.services.bank_finder import find_best_bank
from app.services.loan_application_mutations import save_findback_result

logger = logging.getLogger(__name__)

router = APIRouter(tags=["findback"])

_BUREAUS = {"TU", "XPN", "EFX"}
_MAX_PULLS_PER_APPLICANT_PER_DAY = 3
_MAX_PULLS_PER_ACCOUNT_PER_DAY = 3
_MAX_PULLS_PER_DEALER_PER_DAY = 200


@router.post("/findback")
async def findback(request: Request, customer: dict | None = Depends(optional_customer)) -> dict:
    return await _findback(request, customer)


@asynccontextmanager
async def one_pull_at_a_time(keys: list[str]):
    """Hold advisory locks (applicant, and the account for customer pulls) for
    the whole pull, so the daily-cap checks and the saved row can't be raced by
    parallel requests. A second pull is refused at once rather than queued, so
    a burst can't tie up the connection pool.

    ponytail: no per-dealer lock — it would serialize a whole dealership, and
    the 200/day dealer cap can only overshoot by the dealer's own concurrency.
    Count dealer pulls atomically (one SQL statement) if any dealer goes over the cap."""
    async with get_engine().connect() as conn, conn.begin():
        for key in keys:
            locked = await conn.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": key})
            if not locked:
                raise HTTPException(
                    status_code=429, detail="a credit check for this applicant is already running — wait for it to finish"
                )
        yield


async def _findback(request: Request, customer: dict | None) -> dict:
    """
    Submit a pre-qualification request to 700Credit then run the bank finder
    to return the best rate offer alongside the credit result.

    Callers: dealer-hub (X-Service-Token) or a signed-in customer — never
    anonymous. A customer's email always comes from their session.

    The bank finder step is best-effort: if parameters are missing or the DB
    is unavailable the endpoint still returns the 700Credit result.
    """
    service_caller = is_service_caller(request.headers.get("x-service-token", ""))
    if not service_caller and customer is None:
        raise HTTPException(status_code=401, detail="sign in required")
    customer_email = None if service_caller else customer["email"]

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid request body")

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
        }

    if customer_email:
        payload["email"] = customer_email

    required = ["first_name", "last_name", "address", "city", "state", "zip_code", "email"]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"missing required fields: {', '.join(missing)}",
        )

    bureau = payload.get("bureau") or "TU"
    if bureau not in _BUREAUS:
        raise HTTPException(status_code=400, detail="bureau must be one of TU, XPN, EFX")

    # FCRA: no pull without the consumer's authorization
    if original_payload.get("consent") is not True:
        raise HTTPException(status_code=400, detail="the applicant's consent to a soft credit check is required")

    # dealer_id is trusted only from dealer-hub (service token) — a customer
    # must not be able to attribute a pull to some dealer.
    dealer_id = str(original_payload["dealer_id"])[:20] if service_caller and original_payload.get("dealer_id") else None
    client_ip = _client_ip(request)

    keys = [f"credit-pull-applicant:{payload['first_name']}|{payload['last_name']}|{payload['zip_code']}".lower()]
    if customer_email:
        keys.append(f"credit-pull:{customer_email}")
    async with one_pull_at_a_time(keys):
        return await _pull(payload, original_payload, bureau, service_caller, customer_email, dealer_id, client_ip)


async def _pull(
    payload: dict,
    original_payload: dict,
    bureau: str,
    service_caller: bool,
    customer_email: str | None,
    dealer_id: str | None,
    client_ip: str | None,
) -> dict:
    """Limits, the paid 700Credit pull, bank match and save — under the pull locks."""
    await _enforce_applicant_limit(payload)
    if customer_email:
        await _enforce_account_limit(customer_email)
    if dealer_id:
        await _enforce_dealer_limit(dealer_id)

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
        # requests is blocking — off the event loop so a slow 700Credit can't stall every route
        result = await asyncio.to_thread(
            client.send_prequalify,
            first_name=payload["first_name"],
            last_name=payload["last_name"],
            address=payload["address"],
            city=payload["city"],
            state=payload["state"],
            zip_code=payload["zip_code"],
            bureau=bureau,
            ssn=payload.get("ssn"),
            app_modified=bool(payload.get("app_modified", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("findback request failed")
        raise HTTPException(status_code=502, detail="findback request failed") from exc

    # Only the summary goes back, and only to dealer-hub (the dealer certified
    # consent in an authenticated session). A signed-in customer only gets the
    # offer — returning the score would let an account holder look up a
    # stranger's credit with just a name + address. raw_xml, token and iframe URL never leave the server.
    response: dict = {"prequal": result.public_dict()} if service_caller else {}
    logger.info("findback 700Credit response received")

    # --- Bank Finder (best-effort, does not fail the request if unavailable) ---
    down_payment = _resolve_down_payment(original_payload)
    vehicle_price = _resolve_vehicle_price(original_payload)
    # No score from 700Credit (thin file, decline) = no match, rather than a guessed tier
    credit_score = result.score
    zipcode = payload.get("zip_code")

    # loan_amount is what actually gets financed — vehicle price minus down
    # payment — NOT the down payment itself. Loan program tiers (min/max
    # loan amount) are matched against this, not against down_payment.
    loan_amount = None
    if vehicle_price and vehicle_price > (down_payment or 0):
        loan_amount = vehicle_price - (down_payment or 0)

    best_offer = None
    if loan_amount and credit_score and zipcode:
        try:
            # A dealer's pull only matches banks in their network; if that can't
            # be fetched, offer nothing rather than a bank they don't work with.
            bank_ids = await get_dealer_bank_ids(dealer_id) if dealer_id else None
            async with get_engine().begin() as conn:
                best_offer = await find_best_bank(
                    conn,
                    zipcode=str(zipcode),
                    loan_amount=float(loan_amount),
                    credit_score=int(credit_score),
                    bank_ids=bank_ids,
                )
            if best_offer:
                # The tier and its score bounds reveal the applicant's credit band — dealer-hub only
                response["best_bank"] = best_offer if service_caller else {
                    k: v for k, v in best_offer.items() if k not in ("tier_name", "min_credit_score", "max_credit_score")
                }
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
            p for p, v in [("loan_amount", loan_amount), ("credit_score", credit_score), ("zipcode", zipcode)]
            if not v
        ]
        logger.warning("Bank finder skipped — missing: %s", ", ".join(missing_params))

    # --- Persist user + loan application ---
    # The pull is already paid for, and this row is what the daily caps count
    # and the consent record — so one retry, and a loud log line if it's lost.
    consent_at = datetime.now(timezone.utc)
    for attempt in (1, 2):
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
                    customer_email=customer_email,
                    dealer_id=dealer_id,
                    consent_at=consent_at,
                    client_ip=client_ip,
                )
            response["application_id"] = app_id
            logger.info("Saved loan application id=%d", app_id)
            break
        except Exception:
            if attempt == 1:
                logger.warning("Saving loan application failed — retrying once", exc_info=True)
                continue
            # Enough to reconcile against 700Credit billing without logging the applicant
            logger.error(
                "UNRECORDED CREDIT PULL transid=%s dealer_id=%s customer=%s consent_at=%s client_ip=%s",
                result.transid, dealer_id, bool(customer_email), consent_at.isoformat(), client_ip,
                exc_info=True,
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

async def _count_recent_pulls(where: str, params: dict, what: str) -> int:
    """Pulls in the last 24h matching `where` (a fixed SQL fragment, values bound).
    Fails closed: an unchecked limit means unlimited paid credit pulls."""
    try:
        async with get_engine().connect() as conn:
            return await conn.scalar(
                text(f"SELECT COUNT(*) FROM loan_applications WHERE {where} AND created_at > NOW() - INTERVAL '1 day'"),
                params,
            )
    except Exception as exc:
        logger.exception("%s pull-limit check failed", what)
        raise HTTPException(status_code=503, detail="service temporarily unavailable") from exc


async def _enforce_applicant_limit(payload: dict) -> None:
    """Cap pulls per applicant (name + zip) per day, across all callers and IPs —
    per-IP ingress limits don't stop someone pulling one victim from many IPs."""
    recent = await _count_recent_pulls(
        "lower(first_name) = lower(:first_name) AND lower(last_name) = lower(:last_name) AND zipcode = :zipcode",
        {"first_name": payload["first_name"], "last_name": payload["last_name"], "zipcode": str(payload["zip_code"])},
        "applicant",
    )
    if recent >= _MAX_PULLS_PER_APPLICANT_PER_DAY:
        raise HTTPException(status_code=429, detail="too many credit checks for this applicant today, try again tomorrow")


async def _enforce_account_limit(email: str) -> None:
    """Cap pulls per signed-in account — a verified email proves who owns the
    account, not whose name they typed, so one account can't sweep strangers."""
    recent = await _count_recent_pulls("customer_email = :email", {"email": email}, "account")
    if recent >= _MAX_PULLS_PER_ACCOUNT_PER_DAY:
        raise HTTPException(status_code=429, detail="you've reached today's limit of credit checks")


async def _enforce_dealer_limit(dealer_id: str) -> None:
    """Cap pulls per dealer per day — a stolen dealer login must not mean
    unlimited credit pulls (dealer pulls have no customer session)."""
    recent = await _count_recent_pulls("dealer_id = :dealer_id", {"dealer_id": dealer_id}, "dealer")
    if recent >= _MAX_PULLS_PER_DEALER_PER_DAY:
        logger.warning("dealer %s hit the daily credit-pull cap", dealer_id)
        raise HTTPException(status_code=429, detail="daily credit check limit reached for this dealership")


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
