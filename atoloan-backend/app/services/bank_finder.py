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
    loan_amount: float,
    credit_score: int,
    dti_ratio: Optional[float] = None,
    applicant_membership_paths: Optional[list[str]] = None,
    applicant_conditions: Optional[list[str]] = None,
    ltv_ratio: Optional[float] = None,
    vehicle_mileage: Optional[int] = None,
    vehicle_type: Optional[str] = None,
    vehicle_model_year: Optional[int] = None,
    desired_term_in_months: Optional[int] = None,
    bank_ids: Optional[list[int]] = None,
) -> Optional[dict]:
    """
    Find the best bank with the lowest interest rate for the given criteria.

    Args:
        conn: Database connection
        zipcode: User's zipcode
        loan_amount: The amount to be financed (NOT the down payment) —
            compared against each loan program tier's min/max_loan_amount.
        credit_score: User's credit score
        dti_ratio: Applicant's debt-to-income ratio as a percentage (e.g.
            38.5 for 38.5%), computed from existing monthly debt / monthly
            income. Optional — if None, DTI filtering is skipped entirely
            (a bank with no configured max is always DTI-eligible either way).
        applicant_membership_paths: Which membership eligibility path(s) the
            applicant claims (e.g. ["geographic_common_bond"]), matched
            against each bank's `membership_paths`. Optional — if None,
            membership-path filtering is skipped entirely (geographic
            eligibility is already handled separately via zipcode/
            out_region_list; this only adds the *additional* non-geographic
            paths like employer affinity or family-of-member).
        applicant_conditions: Discount condition_type values the applicant
            qualifies for (e.g. ["autopay", "existing_member"]). Optional —
            if None, no discounts are applied and banks are ranked on base
            rate only, same as before this parameter existed.
        ltv_ratio: Loan-to-value percentage (loan_amount / vehicle_value *
            100), used to apply "ltv_threshold" rate adjustments. Optional.
        vehicle_mileage: Vehicle mileage. Used two ways: (1) eligibility —
            excludes programs whose `mileage_limit_value` the vehicle
            exceeds; (2) pricing — applies "mileage_surcharge" rate
            adjustments. Optional; skipped for both when None.
        vehicle_type: Applicant's vehicle type ("New", "Used", or "Certified
            Pre-Owned"). Optional — if None, programs aren't filtered by
            vehicle type. A program with no vehicle_type on file always
            matches (unknown doesn't exclude).
        vehicle_model_year: Vehicle's model year, checked against each
            program's min_model_year/max_model_year. Optional.
        desired_term_in_months: Applicant's desired loan term. Optional — if
            None, the cheapest term of any length is returned (previous
            behavior). If set, only exact-length term rows are considered.
        bank_ids: Restrict the search to this set of bank ids — e.g. a
            dealer's mapped bank network from dealer-hub-backend. Optional;
            if None, every geographically-eligible bank is considered (same
            as before this parameter existed). An empty list means zero
            eligible banks, distinct from None.

    Returns:
        Dict with best bank info and rate, or None if no eligible bank found
        {
            "bank_id": int,
            "bank_name": str,
            "interest_rate": str,           # base rate as stated by the bank
            "rate_value": float,            # base rate, numeric
            "effective_rate": float,        # base rate net of applied discounts/adjustments
            "applied_conditions": list[str],  # descriptions of discounts/adjustments applied
            "program_name": str,
            "vehicle_type": str,
            "min_model_year": int,
            "max_model_year": int,
            "mileage_limit": int,
            "tier_name": str,
            "term_in_months": int,
            "min_loan_amount": int,
            "max_loan_amount": int
        }
    """
    eligible_banks = await _get_filtered_eligible_banks(
        conn, zipcode, dti_ratio, applicant_membership_paths, bank_ids
    )
    if not eligible_banks:
        return None

    # Find best rate among eligible banks, netting out discounts/adjustments
    # the applicant qualifies for
    best_offer = await _find_best_rate(
        conn,
        eligible_banks,
        loan_amount,
        credit_score,
        applicant_conditions=applicant_conditions,
        ltv_ratio=ltv_ratio,
        vehicle_mileage=vehicle_mileage,
        vehicle_type=vehicle_type,
        vehicle_model_year=vehicle_model_year,
        desired_term_in_months=desired_term_in_months,
    )

    if best_offer:
        logging.info(
            f"[BANK FINDER] Best offer: {best_offer['bank_name']} "
            f"(rate={best_offer['interest_rate']}, effective_rate={best_offer['effective_rate']}, "
            f"program={best_offer['program_name']}, "
            f"tier={best_offer['tier_name']})"
        )
    else:
        logging.warning(f"[BANK FINDER] No suitable offers found for credit_score={credit_score}, loan_amount={loan_amount}")

    return best_offer


async def find_matching_banks(
    conn: AsyncConnection,
    zipcode: str,
    loan_amount: float,
    credit_score: int,
    dti_ratio: Optional[float] = None,
    applicant_membership_paths: Optional[list[str]] = None,
    applicant_conditions: Optional[list[str]] = None,
    ltv_ratio: Optional[float] = None,
    vehicle_mileage: Optional[int] = None,
    vehicle_type: Optional[str] = None,
    vehicle_model_year: Optional[int] = None,
    desired_term_in_months: Optional[int] = None,
    bank_ids: Optional[list[int]] = None,
) -> list[dict]:
    """
    Same eligibility filtering as find_best_bank, but returns every eligible
    bank's best offer (one row per bank — not just the single cheapest
    across all banks), ranked cheapest-effective-rate first.

    Returns an empty list — never None — when nothing matches, since callers
    treat "no matches" as "an empty set of offers" rather than a sentinel.
    """
    eligible_banks = await _get_filtered_eligible_banks(
        conn, zipcode, dti_ratio, applicant_membership_paths, bank_ids
    )
    if not eligible_banks:
        return []

    offers = await _find_all_rates(
        conn,
        eligible_banks,
        loan_amount,
        credit_score,
        applicant_conditions=applicant_conditions,
        ltv_ratio=ltv_ratio,
        vehicle_mileage=vehicle_mileage,
        vehicle_type=vehicle_type,
        vehicle_model_year=vehicle_model_year,
        desired_term_in_months=desired_term_in_months,
    )
    offers.sort(key=lambda o: o["effective_rate"])

    logging.info(f"[BANK FINDER] {len(offers)} matching bank offer(s) for credit_score={credit_score}")
    return offers


async def _get_filtered_eligible_banks(
    conn: AsyncConnection,
    zipcode: str,
    dti_ratio: Optional[float],
    applicant_membership_paths: Optional[list[str]],
    bank_ids: Optional[list[int]],
) -> list[dict]:
    """
    Steps shared by find_best_bank and find_matching_banks: resolve the
    user's county, find geographically-eligible banks, then narrow by dealer
    network / DTI / membership path. Returns [] (not None) as soon as any
    filter empties the set, so callers can early-return uniformly.
    """
    logging.info(
        f"[BANK FINDER] Starting search for zipcode={zipcode}, dti_ratio={dti_ratio}, "
        f"applicant_membership_paths={applicant_membership_paths}"
    )

    # Step 1: Get user's county from zipcode (best-effort). An unknown/
    # unsupported zip code doesn't block the search — it just means we can't
    # match county-restricted banks. Banks with no region restriction (e.g.
    # accept_out_region_loans=true or out_region_list IS NULL) are still
    # eligible everywhere and get checked in step 2 regardless.
    user_county = await _get_county_from_zipcode(conn, zipcode)
    if user_county:
        logging.info(f"[BANK FINDER] User location: zipcode={zipcode}, county={user_county}")
    else:
        logging.warning(
            f"[BANK FINDER] Zipcode {zipcode} not found in database — "
            "only nationwide-eligible banks will be considered"
        )

    # Step 2: Find all eligible banks for this location
    eligible_banks = await _get_eligible_banks(conn, zipcode, user_county)
    if not eligible_banks:
        logging.warning(f"[BANK FINDER] No eligible banks found for zipcode {zipcode}")
        return []

    # Step 2a: Restrict to a dealer's mapped bank network, if given —
    # intersected with (not instead of) geographic eligibility above.
    if bank_ids is not None:
        allowed = set(bank_ids)
        eligible_banks = [b for b in eligible_banks if b["bank_id"] in allowed]
        if not eligible_banks:
            logging.warning(f"[BANK FINDER] No eligible banks left after dealer network filter: {bank_ids}")
            return []

    logging.info(f"[BANK FINDER] Found {len(eligible_banks)} eligible banks")

    # Step 2b: Filter out banks whose max DTI the applicant exceeds. A bank
    # with no configured maximum_debt_to_income_ratio has no DTI cap and
    # always passes. If dti_ratio itself is unknown, DTI filtering is
    # skipped entirely (every bank passes) rather than blocking the search.
    if dti_ratio is not None:
        before_count = len(eligible_banks)
        eligible_banks = [
            b for b in eligible_banks
            if _bank_max_dti(b) is None or dti_ratio <= _bank_max_dti(b)
        ]
        if len(eligible_banks) < before_count:
            logging.info(
                f"[BANK FINDER] DTI filter excluded {before_count - len(eligible_banks)} "
                f"bank(s) for dti_ratio={dti_ratio}"
            )
        if not eligible_banks:
            logging.warning(f"[BANK FINDER] No banks left after DTI filter (dti_ratio={dti_ratio})")
            return []

    # Step 2c: Filter out banks the applicant can't structurally join via any
    # non-geographic membership path. A bank with no membership_paths on file
    # (unknown) or "open_to_all" always passes. If the applicant hasn't
    # claimed a path, this filter is skipped entirely.
    if applicant_membership_paths is not None:
        before_count = len(eligible_banks)
        eligible_banks = [
            b for b in eligible_banks
            if _bank_membership_eligible(b, applicant_membership_paths)
        ]
        if len(eligible_banks) < before_count:
            logging.info(
                f"[BANK FINDER] Membership filter excluded {before_count - len(eligible_banks)} "
                f"bank(s) for applicant_membership_paths={applicant_membership_paths}"
            )
        if not eligible_banks:
            logging.warning(
                f"[BANK FINDER] No banks left after membership filter "
                f"(applicant_membership_paths={applicant_membership_paths})"
            )
            return []

    return eligible_banks


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
    user_county: Optional[str]
) -> list[dict]:
    """
    Get all banks eligible to provide loans in the user's location.

    A bank is eligible if:
    1. accept_out_region_loans is True (eligible for entire USA), OR
    2. accept_out_region_loans is False/NULL but out_region_list is empty/NULL (eligible for entire USA), OR
    3. User's county is in the bank's out_region_list

    user_county may be None (zip code not found in our zipcode table) — in
    that case only banks matching (1) or (2) above can match, since (3)
    can't be evaluated without a known county. This lets nationwide banks
    still be found even for zip codes we don't have county data for.

    Args:
        conn: Database connection
        zipcode: User's zipcode
        user_county: User's county name, or None if unresolved

    Returns:
        List of eligible bank records
    """
    query = text("""
        SELECT
            bank_id,
            name,
            accept_out_region_loans,
            out_region_list,
            maximum_debt_to_income_ratio,
            maximum_debt_to_income_ratio_value,
            membership_paths
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
            "out_region_list": row[3],
            "maximum_debt_to_income_ratio": row[4],
            "maximum_debt_to_income_ratio_value": row[5],
            "membership_paths": row[6]
        })

    return eligible_banks


async def _find_best_rate(
    conn: AsyncConnection,
    eligible_banks: list[dict],
    loan_amount: float,
    credit_score: int,
    applicant_conditions: Optional[list[str]] = None,
    ltv_ratio: Optional[float] = None,
    vehicle_mileage: Optional[int] = None,
    vehicle_type: Optional[str] = None,
    vehicle_model_year: Optional[int] = None,
    desired_term_in_months: Optional[int] = None,
) -> Optional[dict]:
    """
    The single cheapest offer among eligible banks — the min() of what
    _find_all_rates collects across all of them (first-encountered wins
    ties, same as the original strict "<" comparison this replaced).
    """
    offers = await _find_all_rates(
        conn,
        eligible_banks,
        loan_amount,
        credit_score,
        applicant_conditions=applicant_conditions,
        ltv_ratio=ltv_ratio,
        vehicle_mileage=vehicle_mileage,
        vehicle_type=vehicle_type,
        vehicle_model_year=vehicle_model_year,
        desired_term_in_months=desired_term_in_months,
    )
    if not offers:
        return None
    return min(offers, key=lambda o: o["effective_rate"])


async def _find_all_rates(
    conn: AsyncConnection,
    eligible_banks: list[dict],
    loan_amount: float,
    credit_score: int,
    applicant_conditions: Optional[list[str]] = None,
    ltv_ratio: Optional[float] = None,
    vehicle_mileage: Optional[int] = None,
    vehicle_type: Optional[str] = None,
    vehicle_model_year: Optional[int] = None,
    desired_term_in_months: Optional[int] = None,
) -> list[dict]:
    """
    Each eligible bank's single best (cheapest) matching offer — one entry
    per bank, unordered — net of any discounts/rate adjustments the
    applicant qualifies for.

    Args:
        conn: Database connection
        eligible_banks: List of eligible bank records
        loan_amount: The amount to be financed
        credit_score: User's credit score
        applicant_conditions: Discount condition_type values the applicant
            qualifies for. If None, no discounts are applied.
        ltv_ratio: Loan-to-value percentage, used against "ltv_threshold"
            adjustments.
        vehicle_mileage: Vehicle mileage — excludes programs whose mileage
            cap it exceeds, and used against "mileage_surcharge" adjustments.
        vehicle_type: Applicant's vehicle type, matched against each
            program's vehicle_type (a program with none on file always
            matches).
        vehicle_model_year: Vehicle's model year, matched against each
            program's min/max_model_year.
        desired_term_in_months: If set, only term rows of exactly this
            length are considered; if None, the cheapest term of any length
            wins (previous behavior).

    Returns:
        List of offer dicts, one per bank that had an eligible rate.
    """
    offers: list[dict] = []

    # Skip the extra per-bank query entirely when the caller hasn't supplied
    # anything a discount/adjustment could key off — same zero-overhead
    # behavior as before this parameter existed.
    apply_discounts = bool(applicant_conditions) or ltv_ratio is not None or vehicle_mileage is not None

    for bank in eligible_banks:
        bank_id = bank["bank_id"]
        bank_name = bank["name"]

        # Query loan programs for this bank with matching credit score, loan amount,
        # and vehicle/term eligibility.
        # Sorts on COALESCE(rate_value, <numeric cast of rate text>) rather than the raw
        # `rate` TEXT column: sorting TEXT lexicographically ("10.50%" < "9.99%") previously
        # picked the wrong row within a bank whenever rates crossed a digit-count boundary.
        # rate_value is populated at extraction time going forward; the regexp fallback keeps
        # this correct for rows ingested before that column existed.
        # Vehicle/term filters use "param IS NULL OR ..." so each is a no-op when the
        # caller doesn't supply that value, and "column IS NULL OR ..." so an unset
        # program-level bound doesn't wrongly exclude anything (unknown ≠ ineligible).
        query = text("""
            SELECT
                program_name,
                vehicle_type,
                min_model_year,
                max_model_year,
                mileage_limit_value,
                tier_name,
                term_in_months,
                min_loan_amount,
                max_loan_amount,
                rate,
                rate_value,
                min_credit_score,
                max_credit_score
            FROM loan_program_items
            WHERE
                bank_id = :bank_id
                AND item_type = 'term'
                AND min_credit_score <= :credit_score
                AND max_credit_score >= :credit_score
                AND (min_loan_amount IS NULL OR min_loan_amount <= :loan_amount)
                AND (max_loan_amount IS NULL OR max_loan_amount >= :loan_amount)
                AND (CAST(:vehicle_type AS TEXT) IS NULL OR vehicle_type IS NULL OR vehicle_type = CAST(:vehicle_type AS TEXT))
                AND (CAST(:vehicle_model_year AS INTEGER) IS NULL OR min_model_year IS NULL OR min_model_year <= CAST(:vehicle_model_year AS INTEGER))
                AND (CAST(:vehicle_model_year AS INTEGER) IS NULL OR max_model_year IS NULL OR max_model_year >= CAST(:vehicle_model_year AS INTEGER))
                AND (CAST(:vehicle_mileage AS INTEGER) IS NULL OR mileage_limit_value IS NULL OR mileage_limit_value >= CAST(:vehicle_mileage AS INTEGER))
                AND (CAST(:desired_term_in_months AS INTEGER) IS NULL OR term_in_months = CAST(:desired_term_in_months AS INTEGER))
                AND rate IS NOT NULL
            ORDER BY COALESCE(rate_value, NULLIF(regexp_replace(rate, '[^0-9.]', '', 'g'), '')::numeric) ASC
            LIMIT 1
        """)

        result = await conn.execute(query, {
            "bank_id": bank_id,
            "credit_score": credit_score,
            "loan_amount": loan_amount,
            "vehicle_type": vehicle_type,
            "vehicle_model_year": vehicle_model_year,
            "vehicle_mileage": vehicle_mileage,
            "desired_term_in_months": desired_term_in_months,
        })

        row = result.fetchone()

        if row:
            r = row._mapping
            rate_str = r["rate"]
            rate_value = _parse_rate_value(rate_str, r["rate_value"])
            if rate_value is None:
                logging.warning(f"[BANK FINDER] Invalid rate format for {bank_name}: {rate_str}")
                continue

            # Discounts/adjustments are bank-wide policy, not tied to a specific
            # tier/term — a uniform delta applied on top of the already-cheapest
            # base row for this bank, so computing it after picking that row
            # (rather than before) doesn't change which row is "best" within a bank.
            delta = 0.0
            applied: list[str] = []
            if apply_discounts:
                delta, applied = await _compute_rate_delta(
                    conn, bank_id, applicant_conditions, ltv_ratio, vehicle_mileage
                )
            effective_rate = rate_value + delta

            offers.append({
                "bank_id": bank_id,
                "bank_name": bank_name,
                "interest_rate": rate_str,
                "rate_value": rate_value,
                "effective_rate": effective_rate,
                "applied_conditions": applied,
                "program_name": r["program_name"],
                "vehicle_type": r["vehicle_type"],
                "min_model_year": r["min_model_year"],
                "max_model_year": r["max_model_year"],
                "mileage_limit": r["mileage_limit_value"],
                "tier_name": r["tier_name"],
                "term_in_months": r["term_in_months"],
                "min_loan_amount": r["min_loan_amount"],
                "max_loan_amount": r["max_loan_amount"],
                "min_credit_score": r["min_credit_score"],
                "max_credit_score": r["max_credit_score"],
            })

    return offers


def _parse_rate_value(rate_str: Optional[str], rate_value: Optional[float]) -> Optional[float]:
    """Numeric rate, preferring the pre-parsed `rate_value` column and falling
    back to parsing the `rate` text column (legacy rows ingested before
    `rate_value` existed). Returns None if neither is parseable."""
    if rate_value is not None:
        return float(rate_value)
    try:
        return float(rate_str.replace('%', '').strip()) if isinstance(rate_str, str) else float(rate_str)
    except (ValueError, AttributeError, TypeError):
        return None


async def get_term_options_for_offer(
    conn: AsyncConnection,
    bank_id: int,
    program_name: str,
    tier_name: str,
    credit_score: int,
    loan_amount: float,
    rate_delta: float = 0.0,
) -> list[dict]:
    """
    Return every term length available under the specific bank/program/tier
    that `find_best_bank` matched, so callers (e.g. the applicant summary
    email) can show a full rate-by-term table instead of just the single
    cheapest term.

    rate_delta is the same bank-wide discount/adjustment delta `find_best_bank`
    applied to its winning row (effective_rate - rate_value) — applied
    uniformly here too, since discounts aren't tied to a specific term.
    """
    query = text("""
        SELECT term_in_months, rate, rate_value
        FROM loan_program_items
        WHERE bank_id = :bank_id
            AND item_type = 'term'
            AND program_name = :program_name
            AND tier_name = :tier_name
            AND min_credit_score <= :credit_score
            AND max_credit_score >= :credit_score
            AND (min_loan_amount IS NULL OR min_loan_amount <= :loan_amount)
            AND (max_loan_amount IS NULL OR max_loan_amount >= :loan_amount)
            AND rate IS NOT NULL
        ORDER BY term_in_months ASC
    """)
    result = await conn.execute(query, {
        "bank_id": bank_id,
        "program_name": program_name,
        "tier_name": tier_name,
        "credit_score": credit_score,
        "loan_amount": loan_amount,
    })

    options = []
    for row in result.fetchall():
        r = row._mapping
        rate_value = _parse_rate_value(r["rate"], r["rate_value"])
        if rate_value is None:
            continue
        options.append({
            "term_in_months": r["term_in_months"],
            "interest_rate": r["rate"],
            "rate_value": rate_value,
            "effective_rate": round(rate_value + rate_delta, 3),
        })
    return options


async def _compute_rate_delta(
    conn: AsyncConnection,
    bank_id: int,
    applicant_conditions: Optional[list[str]],
    ltv_ratio: Optional[float],
    vehicle_mileage: Optional[int],
) -> tuple[float, list[str]]:
    """
    Sum the percentage-based discounts/adjustments this applicant qualifies
    for at this bank. Discounts always reduce the rate; adjustments can go
    either way (ltv_threshold reduces, mileage_surcharge increases) —
    matching how these were actually observed in sample rate sheets. Only
    percentage-type items are applied here: a fixed_amount value doesn't have
    a well-defined effect on a percentage rate.

    Returns:
        (total_delta, list of applied item descriptions)
    """
    query = text("""
        SELECT item_type, value, value_type, condition_type, threshold_value, description
        FROM rate_policy_items
        WHERE bank_id = :bank_id AND item_type IN ('discount', 'adjustment')
    """)
    result = await conn.execute(query, {"bank_id": bank_id})
    rows = result.fetchall()

    delta = 0.0
    applied: list[str] = []

    for item_type, value, value_type, condition_type, threshold_value, description in rows:
        if value_type != "percentage" or value is None:
            continue
        try:
            pct = float(str(value).replace('%', '').strip())
        except (ValueError, AttributeError):
            continue

        label = description or condition_type or item_type

        if item_type == "discount":
            if applicant_conditions and condition_type in applicant_conditions:
                delta -= pct
                applied.append(label)
        elif item_type == "adjustment":
            if condition_type == "ltv_threshold" and ltv_ratio is not None and threshold_value is not None:
                if ltv_ratio <= float(threshold_value):
                    delta -= pct
                    applied.append(label)
            elif condition_type == "mileage_surcharge" and vehicle_mileage is not None and threshold_value is not None:
                if vehicle_mileage >= float(threshold_value):
                    delta += pct
                    applied.append(label)

    return delta, applied


def _bank_membership_eligible(bank: dict, applicant_membership_paths: list[str]) -> bool:
    """
    True if the applicant qualifies for this bank's membership through at
    least one shared non-geographic path (or the bank is open to all, or the
    bank simply has no membership_paths on file — unknown data doesn't
    exclude a bank, it just means this filter can't rule it out).
    """
    bank_paths = bank.get("membership_paths") or []
    if not bank_paths or "open_to_all" in bank_paths:
        return True
    return bool(set(bank_paths) & set(applicant_membership_paths))


def _bank_max_dti(bank: dict) -> Optional[float]:
    """
    Prefer the numeric `maximum_debt_to_income_ratio_value` column
    (populated at extraction time as of the rate_sheet_parser schema
    optimization) over re-parsing the free-text column at query time.
    Falls back to text parsing only for rows ingested before that column
    existed, until that bank's rate sheet is re-uploaded.
    """
    value = bank.get("maximum_debt_to_income_ratio_value")
    if value is not None:
        return float(value)
    return _parse_dti_percentage(bank.get("maximum_debt_to_income_ratio"))


def _parse_dti_percentage(value: Optional[str]) -> Optional[float]:
    """
    Parse a bank's maximum_debt_to_income_ratio (free-text, e.g. "45%",
    "45", "0.45") into a percentage float (45.0). Returns None if unset or
    unparseable, which callers treat as "no DTI cap configured".
    """
    if not value:
        return None
    cleaned = str(value).replace("%", "").strip()
    try:
        parsed = float(cleaned)
    except ValueError:
        logging.warning(f"[BANK FINDER] Invalid maximum_debt_to_income_ratio: {value}")
        return None
    # Values like 0.45 mean 45% — normalize to a percentage scale.
    return parsed * 100 if parsed <= 1 else parsed
