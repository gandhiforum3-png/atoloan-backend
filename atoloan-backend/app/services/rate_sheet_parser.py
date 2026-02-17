"""
Rate Sheet Markdown Parser Service

This module provides functions to parse markdown text from rate sheets
and extract structured data using LLM with structured output.
"""

import logging
import os
from typing import List, Optional
from datetime import date

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

from app.models.rate_sheet import (
    CreditUnionRateSheet,
    CreditUnionInfo,
    RatePolicy,
    Guidelines,
    SpecialPrograms,
    ParticipationAndFunding,
    AdditionalDetails,
    LoanProgram,
    LoanTier,
    TermOption,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# HELPER: BASE LLM FACTORY
# ---------------------------------------------------------

def make_llm() -> ChatOpenAI:
    """
    Create a base ChatOpenAI instance.
    Reads OPENAI_API_KEY from environment variables.
    
    Environment Variables:
        OPENAI_API_KEY: OpenAI API key (required)
    
    Returns:
        ChatOpenAI: Configured LLM instance
        
    Raises:
        ValueError: If OPENAI_API_KEY is not set
    """
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY environment variable is not set. "
            "Please set it in your .env file or environment: "
            "export OPENAI_API_KEY='sk-...'"
        )
    
    if not api_key.startswith("sk-"):
        logger.warning(
            "OPENAI_API_KEY does not start with 'sk-'. "
            "This may not be a valid OpenAI key format."
        )
    
    return ChatOpenAI(
        api_key=api_key,
        model="gpt-4o-mini",
        temperature=0.1,
        max_tokens=4096,
    )


# ---------------------------------------------------------
# SECTION-SPECIFIC EXTRACTORS (STRUCTURED)
# ---------------------------------------------------------

def extract_credit_union_info(text: str, llm: ChatOpenAI) -> Optional[CreditUnionInfo]:
    """Extract general credit union information from markdown text."""
    prompt = PromptTemplate(
        template="""
You are an expert financial document parser specializing in U.S. credit union and bank rate sheets.

From the TEXT below, extract ONLY the **general credit union information** and map it to the `CreditUnionInfo` model.

Guidelines:
- Extract: name, effective_date, replaces_rate_sheet_date, address.
- Extract: contact phone, fax, email, website.
- Combine all buyer/funder/staff contact names + titles + phones into `contact_person`.
- Extract membership eligibility text.
- If membership is required to get a loan, set `is_credit_union_member_required = true`.
- List branch locations if present.
- If cosigners are allowed, set `is_cosigner_allowed = true`.
- If cosigner must have same address, set `is_cosigner_same_address_required = true`.
- Put all cosigner/borrower rules in `cosigner_requirement_guidelines`.
- Extract any stated max DTI into `maximum_debt_to_income_ratio`.
- Extract all allowed regions/cities/counties mentioned for membership and store in `out_region_list`.
- Set `accept_out_region_loans` based on whether out-of-region borrowers are allowed.
- Use ISO 8601 dates (YYYY-MM-DD) for dates.
- Use `null` for any field that is truly missing.

Return a single `CreditUnionInfo` object.

────────────────────
TEXT:
{text}
""",
        input_variables=["text"],
    )

    try:
        structured_llm = llm.with_structured_output(CreditUnionInfo, method="function_calling")
        result = structured_llm.invoke(prompt.format(text=text))
        logger.info(f"Successfully extracted CreditUnionInfo: {result.name if result else 'None'}")
        return result
    except Exception as e:
        logger.error(f"Failed to extract CreditUnionInfo: {e}")
        return None


def extract_rate_policy(text: str, llm: ChatOpenAI) -> Optional[RatePolicy]:
    """Extract rate policy information from markdown text."""
    prompt = PromptTemplate(
        template="""
You are an expert financial document parser.

From the TEXT below, extract ONLY the **rate policy** and map it to the `RatePolicy` model.

Guidelines:
- base_discount: rate floor / base rate / base discount text (e.g., "4.99% floor").
- available_discounts: autopay, EV, direct deposit, membership, etc.
  - Fill `description`, `value` (e.g., "0.25%") and `value_type` ("percentage" or "fixed_amount").
  - Put any conditions into `conditions`.
- available_rate_adjustments: LTV add-ons, long-term premiums, mileage adjustments, etc.
  - Same structure as discounts.
- fees: dealer flat, SMART fee, backend service fees, etc.
  - `type`, `value`, `value_type`, `description`.
- donations_or_benefits: text about community donations, member rewards, or similar.

Return a single `RatePolicy` object.

────────────────────
TEXT:
{text}
""",
        input_variables=["text"],
    )

    try:
        structured_llm = llm.with_structured_output(RatePolicy, method="function_calling")
        result = structured_llm.invoke(prompt.format(text=text))
        logger.info("Successfully extracted RatePolicy")
        return result
    except Exception as e:
        logger.error(f"Failed to extract RatePolicy: {e}")
        return None


def extract_guidelines(text: str, llm: ChatOpenAI) -> Optional[Guidelines]:
    """Extract underwriting guidelines from markdown text."""
    prompt = PromptTemplate(
        template="""
You are an expert financial document parser.

From the TEXT below, extract ONLY **underwriting guidelines and qualifications** and map them to `Guidelines`.

Map as follows:
- income_requirements: minimum income, income stability, or verification rules.
- debt_ratio_limits: any DTI or PTI limits (e.g., "Max 45% DTI").
- vehicle_restrictions: ineligible vehicles (e.g., salvage titles, commercial, branded titles, mileage caps).
- proof_of_income_rules: when proof of income is needed (e.g., "Required when FICO <= 660").
- underwriting_rules: repossession/bankruptcy rules, open auto guidelines, time since derogatory events, etc.
- credit_bureau_used: e.g., "Experian FICO 8".
- documentation_required: list of required docs (DL, SSN card, proof of insurance, etc.).
- notes: any other misc underwriting commentary.

Return a single `Guidelines` object.

────────────────────
TEXT:
{text}
""",
        input_variables=["text"],
    )

    try:
        structured_llm = llm.with_structured_output(Guidelines, method="function_calling")
        result = structured_llm.invoke(prompt.format(text=text))
        logger.info("Successfully extracted Guidelines")
        return result
    except Exception as e:
        logger.error(f"Failed to extract Guidelines: {e}")
        return None


def extract_special_programs(text: str, llm: ChatOpenAI) -> Optional[SpecialPrograms]:
    """Extract special loan programs from markdown text."""
    prompt = PromptTemplate(
        template="""
You are an expert financial document parser.

From the TEXT below, extract ONLY **special loan programs** and map them to `SpecialPrograms`.

Map as follows:
- First time buyer programs:
  - Set `first_time_buyer.is_first_time_buyer_participant` to true if any such program exists.
  - Fill description, max_amount, max_term, ltv, fico_pricing, requirements.
  - Put any bullet-point rules into `first_time_buyer_guideline`.
- Sub-prime / Re-Start / 2nd Chance / Non-prime programs:
  - Map to `sub_prime`.
  - Fill description, fico_limit, max_amount, max_term, ltv, income_proof_required, auto_history_requirement.

If no such programs are mentioned, all fields may be null.

Return a single `SpecialPrograms` object.

────────────────────
TEXT:
{text}
""",
        input_variables=["text"],
    )

    try:
        structured_llm = llm.with_structured_output(SpecialPrograms, method="function_calling")
        result = structured_llm.invoke(prompt.format(text=text))
        logger.info("Successfully extracted SpecialPrograms")
        return result
    except Exception as e:
        logger.error(f"Failed to extract SpecialPrograms: {e}")
        return None


def extract_participation_and_funding(text: str, llm: ChatOpenAI) -> Optional[ParticipationAndFunding]:
    """Extract participation and funding information from markdown text."""
    prompt = PromptTemplate(
        template="""
You are an expert financial document parser.

From the TEXT below, extract ONLY **dealer participation, funding, and lienholder** information
and map them to `ParticipationAndFunding`.

Mapping:
- dealer_participation:
  - percentage: dealer flat %
  - minimum / maximum: min/max payout
  - conditions: textual conditions.
- chargeback_policy:
  - early payoff penalties, dealer liability, etc.
- funding:
  - method: ACH, SmartFund, etc.
  - contact_email, contact_phone, hours, address.
- lien_holder_info:
  - name, mailing_address, physical_address, insurance_address, electronic_lien_code.

Return a single `ParticipationAndFunding` object.

────────────────────
TEXT:
{text}
""",
        input_variables=["text"],
    )

    try:
        structured_llm = llm.with_structured_output(ParticipationAndFunding, method="function_calling")
        result = structured_llm.invoke(prompt.format(text=text))
        logger.info("Successfully extracted ParticipationAndFunding")
        return result
    except Exception as e:
        logger.error(f"Failed to extract ParticipationAndFunding: {e}")
        return None


def extract_additional_details(text: str, llm: ChatOpenAI) -> Optional[AdditionalDetails]:
    """Extract disclaimers and additional details from markdown text."""
    prompt = PromptTemplate(
        template="""
You are an expert financial document parser.

From the TEXT below, extract ONLY **disclaimers and misc notes** and map them to `AdditionalDetails`.

Mapping:
- disclaimers: list of all disclaimer / legal / boilerplate text lines.
- rate_change_policy: explicit rate change policy, or a default like "Rates subject to change without prior notice." if present.
- eligibility_notes: misc eligibility or membership notes not captured elsewhere.
- other_comments: any other useful info that doesn't fit other models.

Return a single `AdditionalDetails` object.

────────────────────
TEXT:
{text}
""",
        input_variables=["text"],
    )

    try:
        structured_llm = llm.with_structured_output(AdditionalDetails, method="function_calling")
        result = structured_llm.invoke(prompt.format(text=text))
        logger.info("Successfully extracted AdditionalDetails")
        return result
    except Exception as e:
        logger.error(f"Failed to extract AdditionalDetails: {e}")
        return None


# ---------------------------------------------------------
# LOAN PROGRAM DISCOVERY + PER-PROGRAM EXTRACTION
# ---------------------------------------------------------

class LoanProgramStub(BaseModel):
    """
    A lightweight description of a loan program group
    that we will later expand into a full LoanProgram.
    """
    program_name: str = Field(..., description="Human-readable label like 'Auto Loan – < 2 Years'")
    vehicle_type: Optional[str] = Field(None, description="Hint: New or Used if obvious.")
    model_year_range: Optional[str] = Field(None, description="Hint: e.g. '< 2 Years', '2019-2022', '2023+'")


class LoanProgramCatalog(BaseModel):
    """Container for discovered loan programs."""
    programs: List[LoanProgramStub]


def discover_loan_programs(text: str, llm: ChatOpenAI) -> List[LoanProgramStub]:
    """
    First pass: identify all distinct loan program groups without extracting full tables.
    """
    discovery_prompt = PromptTemplate(
        template="""
You are an expert at reading auto loan rate sheets.

From the TEXT below, identify all distinct loan program groups.
Examples of program groups:
- New Auto < 2 Years
- Used Auto 3-6 Years (2019-2022)
- Auto Loan – 2023+
- 7-9 Years, 2016-2018, etc.

Your job in this step is ONLY to list the program "headers", not the full pricing.

Return JSON that matches the following model:

LoanProgramCatalog:
- programs: List[LoanProgramStub]

LoanProgramStub:
- program_name: human readable label exactly as it appears (or very close).
- vehicle_type: "New" or "Used" if you can infer it, else null.
- model_year_range: the raw model year or age range text (e.g., "< 2 Years", "2019-2022", "2023+").

Do NOT include any interest rates, tiers, or term data here.

TEXT:
{text}
""",
        input_variables=["text"],
    )

    try:
        structured_llm = llm.with_structured_output(LoanProgramCatalog, method="function_calling")
        catalog: LoanProgramCatalog = structured_llm.invoke(discovery_prompt.format(text=text))
        logger.info(f"Discovered {len(catalog.programs)} loan programs")
        return catalog.programs
    except Exception as e:
        logger.error(f"Failed to discover loan programs: {e}")
        return []


def extract_single_loan_program(
    text: str,
    llm: ChatOpenAI,
    stub: LoanProgramStub,
    current_year: int = 2025,
) -> Optional[LoanProgram]:
    """
    Second pass: for one specific loan program group, extract the full LoanProgram object.
    """
    extraction_prompt = PromptTemplate(
        template="""
You are an expert financial document parser specializing in auto loan rate sheets.

Your task now is to extract the FULL details for exactly ONE loan program from the TEXT.

Program to focus on:
- program_name: {program_name}
- vehicle_type (hint): {vehicle_type}
- model_year_range (hint): {model_year_range}

Ignore all other programs or tables. Only parse the program that best matches the hints above.

Map the information to the `LoanProgram` model:

- program_name: use a clear label, ideally matching the header (e.g., "Auto Loan – 2019-2022").
- vehicle_type: "New" or "Used".
- model_year_range: raw text (e.g., "< 2 Years", "3-6 Years", "2019-2022", "2023+").
- min_model_year / max_model_year:
  - If explicit range like "2019-2022": min=2019, max=2022.
  - If age-based range like "< 2 Years", "3-6 Years", etc. use CURRENT_YEAR = {current_year}:
    - "< 2 Years" → min_model_year = current_year - 2 + 1, max_model_year = current_year
    - "3–6 Years" → min_model_year = current_year - 6, max_model_year = current_year - 3
    - "10+ Years" → max_model_year = current_year - 10, min_model_year may be null.
- mileage_limit: maximum mileage if defined.
- ltv_details: base_ltv, max_ltv, and notes for that program.

For each credit tier in this program:
- Create a LoanTier.
- tier_name: label like "Platinum", "Gold", "Member", "Standard", "No Score", "Re-Start", "2nd Chance".
- credit_score_range: e.g., "740+", "700-739", "< 619".
- min_credit_score / max_credit_score:
  - Use 850 as max for any open-ended high tier (e.g., "740+").
  - Use 0 as min for open-ended low tier (e.g., "< 600").
- term_options:
  - For each term row (36, 48, 60, 72, 84, 96 months):
    - term_in_months: use the term month.
    - min_loan_amount / max_loan_amount: convert USD amounts to integers (no commas).
    - rate: exact interest rate text (e.g., "4.99%").
    - conditions: any notes like "up to 125% LTV", "EV only", etc.

Preserve all term rows for this specific program.
Do NOT merge data from other age ranges or vehicle types into this program.

Return a single `LoanProgram` object.

────────────────────
TEXT:
{text}
""",
        input_variables=["text"],
    )

    try:
        structured_llm = llm.with_structured_output(LoanProgram, method="function_calling")
        result = structured_llm.invoke(
            extraction_prompt.format(
                text=text,
                program_name=stub.program_name,
                vehicle_type=stub.vehicle_type or "null",
                model_year_range=stub.model_year_range or "null",
                current_year=current_year,
            )
        )
        logger.info(f"Successfully extracted LoanProgram: {stub.program_name}")
        return result
    except Exception as e:
        logger.error(f"Failed to extract LoanProgram '{stub.program_name}': {e}")
        return None


def extract_all_loan_programs(text: str, llm: ChatOpenAI, current_year: int = 2025) -> List[LoanProgram]:
    """
    Orchestrates discovery + per-program extraction.
    """
    stubs = discover_loan_programs(text, llm)
    programs: List[LoanProgram] = []

    for stub in stubs:
        program = extract_single_loan_program(text, llm, stub, current_year=current_year)
        if program:
            programs.append(program)

    logger.info(f"Successfully extracted {len(programs)} loan programs")
    return programs


# ---------------------------------------------------------
# TOP-LEVEL: FULL MULTI-STEP PIPELINE
# ---------------------------------------------------------

def parse_rate_sheet_from_markdown(text: str, current_year: int = 2025) -> Optional[CreditUnionRateSheet]:
    """
    Main entry point: runs the multi-step hybrid agent
    and returns a fully populated CreditUnionRateSheet.
    
    Args:
        text: Markdown text from the rate sheet
        current_year: Year to use for calculating model years from age ranges
        
    Returns:
        CreditUnionRateSheet object or None if parsing fails
    """
    if not text or not isinstance(text, str) or not text.strip():
        logger.error("Invalid input: text must be a non-empty string")
        return None

    try:
        llm = make_llm()

        # Step 1: top-level sections
        logger.info("Extracting credit union info...")
        credit_union_info = extract_credit_union_info(text, llm)

        logger.info("Extracting rate policy...")
        rate_policy = extract_rate_policy(text, llm)

        logger.info("Extracting guidelines...")
        guidelines = extract_guidelines(text, llm)

        logger.info("Extracting special programs...")
        special_programs = extract_special_programs(text, llm)

        logger.info("Extracting participation and funding...")
        participation_and_funding = extract_participation_and_funding(text, llm)

        logger.info("Extracting additional details...")
        additional_details = extract_additional_details(text, llm)

        # Step 2: loan programs (multi-step: discover → per-program)
        logger.info("Discovering and extracting loan programs...")
        loan_programs = extract_all_loan_programs(text, llm, current_year=current_year)

        # Step 3: assemble final object
        rate_sheet = CreditUnionRateSheet(
            credit_union_info=credit_union_info,
            rate_policy=rate_policy,
            loan_programs=loan_programs,
            guidelines=guidelines,
            special_programs=special_programs,
            participation_and_funding=participation_and_funding,
            additional_details=additional_details,
        )

        logger.info("Successfully parsed rate sheet")
        return rate_sheet

    except Exception as e:
        logger.error(f"Failed to parse rate sheet: {e}", exc_info=True)
        return None
