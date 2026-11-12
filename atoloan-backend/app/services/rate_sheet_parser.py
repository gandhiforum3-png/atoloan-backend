"""
Rate Sheet PDF Parser Service

Sends the rate sheet PDF straight to Claude and gets back a validated
CreditUnionRateSheet via structured outputs — no local PDF→markdown step.
"""

import base64
import logging
from datetime import date

import anthropic

from app.core.config import get_settings
from app.models.rate_sheet import CreditUnionRateSheet

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """
You are an expert financial document parser specializing in U.S. credit union and bank auto loan rate sheets.
Extract everything in the attached rate sheet into the `CreditUnionRateSheet` schema. Use null for anything truly missing.
Use ISO 8601 dates (YYYY-MM-DD).

credit_union_info:
- name, effective_date, replaces_rate_sheet_date, address; contact phone, fax, email, website.
- Combine all buyer/funder/staff contact names + titles + phones into `contact_person`.
- Membership eligibility text; set `is_credit_union_member_required` if membership is required to get a loan.
- Branch locations if present.
- Cosigners: `is_cosigner_allowed`, `is_cosigner_same_address_required`, and all cosigner/borrower rules in `cosigner_requirement_guidelines`.
- Any stated max DTI in `maximum_debt_to_income_ratio`.
- All allowed regions/cities/counties in `out_region_list`; `accept_out_region_loans` per whether out-of-region borrowers are allowed.

rate_policy:
- base_discount: rate floor / base rate / base discount text (e.g. "4.99% floor").
- available_discounts (autopay, EV, direct deposit, membership, ...) and available_rate_adjustments
  (LTV add-ons, long-term premiums, mileage adjustments, ...): description, value (e.g. "0.25%"),
  value_type ("percentage" or "fixed_amount"), conditions.
- fees (dealer flat, SMART fee, backend service fees, ...): type, value, value_type, description.
- donations_or_benefits: community donations, member rewards, or similar.

loan_programs — one entry per distinct program group (e.g. "New Auto < 2 Years", "Used Auto 2019-2022", "2023+"):
- program_name as it appears; vehicle_type "New" or "Used"; model_year_range as raw text.
- min_model_year / max_model_year: explicit ranges map directly ("2019-2022" → 2019, 2022). For age-based ranges
  use CURRENT_YEAR: "< 2 Years" → min = CURRENT_YEAR - 1, max = CURRENT_YEAR; "3-6 Years" → min = CURRENT_YEAR - 6,
  max = CURRENT_YEAR - 3; "10+ Years" → max = CURRENT_YEAR - 10, min null.
- mileage_limit; ltv_details (base_ltv, max_ltv, notes).
- loan_tiers: one per credit tier (Platinum, Gold, "740+", No Score, Re-Start, 2nd Chance, ...). credit_score_range as
  printed; min/max_credit_score with 850 as max for open-ended top tiers and 0 as min for open-ended bottom tiers.
- term_options: every term row (36, 48, 60, 72, 84, 96 months...) with term_in_months, min/max_loan_amount as integer
  dollars, rate as printed (e.g. "4.99%"), and conditions such as "up to 125% LTV" or "EV only".
- Preserve every program, tier, and term. Never merge data across age ranges or vehicle types.

guidelines: income_requirements, debt_ratio_limits (DTI/PTI), vehicle_restrictions (salvage, commercial, branded titles,
mileage caps), proof_of_income_rules, underwriting_rules (repossession/bankruptcy, open autos, time since derogatory
events), credit_bureau_used (e.g. "Experian FICO 8"), documentation_required, notes.

special_programs:
- first_time_buyer: set is_first_time_buyer_participant if such a program exists; description, max_amount, max_term,
  ltv, fico_pricing, requirements; bullet rules in first_time_buyer_guideline.
- sub_prime (Re-Start / 2nd Chance / non-prime): description, fico_limit, max_amount, max_term, ltv,
  income_proof_required, auto_history_requirement.

participation_and_funding: dealer_participation (percentage, minimum, maximum, conditions); chargeback_policy;
funding (method, contact_email, contact_phone, hours, address); lien_holder_info (name, mailing_address,
physical_address, insurance_address, electronic_lien_code).

additional_details: disclaimers, rate_change_policy, eligibility_notes, other_comments.
""".strip()


async def parse_rate_sheet_pdf(pdf_bytes: bytes, current_year: int | None = None) -> CreditUnionRateSheet:
    """Parse a rate sheet PDF into a CreditUnionRateSheet. Raises on API errors or an unusable response."""
    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set. Add it to your .env file: ANTHROPIC_API_KEY=sk-ant-...")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    # Streaming: a full rate sheet (programs × tiers × terms) can run to tens of thousands of output tokens.
    async with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(pdf_bytes).decode(),
                    },
                },
                {"type": "text", "text": f"CURRENT_YEAR = {current_year or date.today().year}"},
            ],
        }],
        output_format=CreditUnionRateSheet,
    ) as stream:
        message = await stream.get_final_message()

    if message.stop_reason == "refusal":
        category = message.stop_details.category if message.stop_details else None
        raise ValueError(f"Claude declined to parse the rate sheet (category: {category}, request {message._request_id})")
    if message.stop_reason == "max_tokens":
        raise ValueError(f"Rate sheet output was truncated at max_tokens (request {message._request_id})")
    if message.parsed_output is None:
        raise ValueError(f"Claude returned no structured rate sheet (request {message._request_id})")

    sheet = message.parsed_output
    logger.info(
        "Parsed rate sheet for %s: %d loan programs (request %s)",
        sheet.credit_union_info.name if sheet.credit_union_info else None,
        len(sheet.loan_programs or []),
        message._request_id,
    )
    return sheet
