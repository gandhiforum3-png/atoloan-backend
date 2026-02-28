"""
Credit Union Mutations Service
Handles all PostgreSQL INSERT/UPSERT operations for credit unions, rate policies, and loan programs.
"""
import logging
from datetime import date, datetime
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


def parse_date_string(date_str: Optional[str]) -> Optional[date]:
    """
    Parse a date string in ISO format (YYYY-MM-DD) to a Python date object.
    Returns None if the input is None or invalid.
    """
    if not date_str:
        return None

    if isinstance(date_str, date):
        return date_str

    try:
        # Parse ISO format date string (YYYY-MM-DD)
        return datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        logging.warning(f"Failed to parse date string: {date_str}")
        return None


async def upsert_bank_info(conn: AsyncConnection, rate_sheet_data: dict) -> int:
    """
    Upsert bank_info table and return bank_id.

    Args:
        conn: Database connection
        rate_sheet_data: Complete rate sheet data dict

    Returns:
        Bank ID of upserted record
    """
    credit_union_info = rate_sheet_data.get("credit_union_info") or {}
    guidelines = rate_sheet_data.get("guidelines") or {}
    special_programs = rate_sheet_data.get("special_programs") or {}
    participation = rate_sheet_data.get("participation_and_funding") or {}
    additional = rate_sheet_data.get("additional_details") or {}

    contact = credit_union_info.get("contact") or {}
    ftb = special_programs.get("first_time_buyer") or {}
    subprime = special_programs.get("sub_prime") or {}
    dealer_participation = participation.get("dealer_participation") or {}
    funding = participation.get("funding") or {}
    lien_holder = participation.get("lien_holder_info") or {}

    bank_name = credit_union_info.get("name")
    if not bank_name:
        raise ValueError("Bank name is required for upsert")

    query = text("""
        INSERT INTO bank_info (
            name, effective_date, replaces_rate_sheet_date, address,
            contact_phone, contact_fax, contact_email, contact_website,
            contact_person, membership_eligibility, branch_locations, notes,
            maximum_debt_to_income_ratio, is_cosigner_allowed, is_cosigner_same_address_required,
            cosigner_requirement_guidelines, accept_out_region_loans, out_region_list,
            is_credit_union_member_required,
            ftd_is_participant, ftd_guidelines, ftd_description, ftd_max_amount,
            ftd_max_term, ftd_ltv, ftd_fico_pricing, ftd_requirements,
            subprime_description, subprime_fico_limit, subprime_max_amount, subprime_max_term,
            subprime_ltv, subprime_income_proof_required, subprime_auto_history_requirement,
            dealer_participation_percentage, dealer_participation_minimum, dealer_participation_maximum,
            dealer_participation_conditions, chargeback_policy,
            funding_method, funding_contact_email, funding_contact_phone, funding_hours, funding_address,
            lien_holder_name, lien_holder_mailing_address, lien_holder_physical_address,
            lien_holder_insurance_address, lien_holder_electronic_lien_code,
            disclaimers, rate_change_policy, eligibility_notes, other_comments,
            updated_at
        )
        VALUES (
            :name, :effective_date, :replaces_rate_sheet_date, :address,
            :contact_phone, :contact_fax, :contact_email, :contact_website,
            :contact_person, :membership_eligibility, :branch_locations, :notes,
            :maximum_debt_to_income_ratio, :is_cosigner_allowed, :is_cosigner_same_address_required,
            :cosigner_requirement_guidelines, :accept_out_region_loans, :out_region_list,
            :is_credit_union_member_required,
            :ftd_is_participant, :ftd_guidelines, :ftd_description, :ftd_max_amount,
            :ftd_max_term, :ftd_ltv, :ftd_fico_pricing, :ftd_requirements,
            :subprime_description, :subprime_fico_limit, :subprime_max_amount, :subprime_max_term,
            :subprime_ltv, :subprime_income_proof_required, :subprime_auto_history_requirement,
            :dealer_participation_percentage, :dealer_participation_minimum, :dealer_participation_maximum,
            :dealer_participation_conditions, :chargeback_policy,
            :funding_method, :funding_contact_email, :funding_contact_phone, :funding_hours, :funding_address,
            :lien_holder_name, :lien_holder_mailing_address, :lien_holder_physical_address,
            :lien_holder_insurance_address, :lien_holder_electronic_lien_code,
            :disclaimers, :rate_change_policy, :eligibility_notes, :other_comments,
            NOW()
        )
        ON CONFLICT (name) DO UPDATE SET
            effective_date = EXCLUDED.effective_date,
            replaces_rate_sheet_date = EXCLUDED.replaces_rate_sheet_date,
            address = EXCLUDED.address,
            contact_phone = EXCLUDED.contact_phone,
            contact_fax = EXCLUDED.contact_fax,
            contact_email = EXCLUDED.contact_email,
            contact_website = EXCLUDED.contact_website,
            contact_person = EXCLUDED.contact_person,
            membership_eligibility = EXCLUDED.membership_eligibility,
            branch_locations = EXCLUDED.branch_locations,
            notes = EXCLUDED.notes,
            maximum_debt_to_income_ratio = EXCLUDED.maximum_debt_to_income_ratio,
            is_cosigner_allowed = EXCLUDED.is_cosigner_allowed,
            is_cosigner_same_address_required = EXCLUDED.is_cosigner_same_address_required,
            cosigner_requirement_guidelines = EXCLUDED.cosigner_requirement_guidelines,
            accept_out_region_loans = EXCLUDED.accept_out_region_loans,
            out_region_list = EXCLUDED.out_region_list,
            is_credit_union_member_required = EXCLUDED.is_credit_union_member_required,
            ftd_is_participant = EXCLUDED.ftd_is_participant,
            ftd_guidelines = EXCLUDED.ftd_guidelines,
            ftd_description = EXCLUDED.ftd_description,
            ftd_max_amount = EXCLUDED.ftd_max_amount,
            ftd_max_term = EXCLUDED.ftd_max_term,
            ftd_ltv = EXCLUDED.ftd_ltv,
            ftd_fico_pricing = EXCLUDED.ftd_fico_pricing,
            ftd_requirements = EXCLUDED.ftd_requirements,
            subprime_description = EXCLUDED.subprime_description,
            subprime_fico_limit = EXCLUDED.subprime_fico_limit,
            subprime_max_amount = EXCLUDED.subprime_max_amount,
            subprime_max_term = EXCLUDED.subprime_max_term,
            subprime_ltv = EXCLUDED.subprime_ltv,
            subprime_income_proof_required = EXCLUDED.subprime_income_proof_required,
            subprime_auto_history_requirement = EXCLUDED.subprime_auto_history_requirement,
            dealer_participation_percentage = EXCLUDED.dealer_participation_percentage,
            dealer_participation_minimum = EXCLUDED.dealer_participation_minimum,
            dealer_participation_maximum = EXCLUDED.dealer_participation_maximum,
            dealer_participation_conditions = EXCLUDED.dealer_participation_conditions,
            chargeback_policy = EXCLUDED.chargeback_policy,
            funding_method = EXCLUDED.funding_method,
            funding_contact_email = EXCLUDED.funding_contact_email,
            funding_contact_phone = EXCLUDED.funding_contact_phone,
            funding_hours = EXCLUDED.funding_hours,
            funding_address = EXCLUDED.funding_address,
            lien_holder_name = EXCLUDED.lien_holder_name,
            lien_holder_mailing_address = EXCLUDED.lien_holder_mailing_address,
            lien_holder_physical_address = EXCLUDED.lien_holder_physical_address,
            lien_holder_insurance_address = EXCLUDED.lien_holder_insurance_address,
            lien_holder_electronic_lien_code = EXCLUDED.lien_holder_electronic_lien_code,
            disclaimers = EXCLUDED.disclaimers,
            rate_change_policy = EXCLUDED.rate_change_policy,
            eligibility_notes = EXCLUDED.eligibility_notes,
            other_comments = EXCLUDED.other_comments,
            updated_at = NOW()
        RETURNING bank_id
    """)

    result = await conn.execute(query, {
        "name": bank_name,
        "effective_date": parse_date_string(credit_union_info.get("effective_date")),
        "replaces_rate_sheet_date": parse_date_string(credit_union_info.get("replaces_rate_sheet_date")),
        "address": credit_union_info.get("address"),
        "contact_phone": contact.get("phone"),
        "contact_fax": contact.get("fax"),
        "contact_email": contact.get("email"),
        "contact_website": contact.get("website"),
        "contact_person": credit_union_info.get("contact_person"),
        "membership_eligibility": credit_union_info.get("membership_eligibility"),
        "branch_locations": credit_union_info.get("branch_locations"),
        "notes": credit_union_info.get("notes"),
        "maximum_debt_to_income_ratio": credit_union_info.get("maximum_debt_to_income_ratio"),
        "is_cosigner_allowed": credit_union_info.get("is_cosigner_allowed"),
        "is_cosigner_same_address_required": credit_union_info.get("is_cosigner_same_address_required"),
        "cosigner_requirement_guidelines": credit_union_info.get("cosigner_requirement_guidelines"),
        "accept_out_region_loans": credit_union_info.get("accept_out_region_loans"),
        "out_region_list": credit_union_info.get("out_region_list"),
        "is_credit_union_member_required": credit_union_info.get("is_credit_union_member_required"),
        "ftd_is_participant": ftb.get("is_first_time_buyer_participant"),
        "ftd_guidelines": ftb.get("first_time_buyer_guideline"),
        "ftd_description": ftb.get("description"),
        "ftd_max_amount": ftb.get("max_amount"),
        "ftd_max_term": ftb.get("max_term"),
        "ftd_ltv": ftb.get("ltv"),
        "ftd_fico_pricing": ftb.get("fico_pricing"),
        "ftd_requirements": ftb.get("requirements"),
        "subprime_description": subprime.get("description"),
        "subprime_fico_limit": subprime.get("fico_limit"),
        "subprime_max_amount": subprime.get("max_amount"),
        "subprime_max_term": subprime.get("max_term"),
        "subprime_ltv": subprime.get("ltv"),
        "subprime_income_proof_required": subprime.get("income_proof_required"),
        "subprime_auto_history_requirement": subprime.get("auto_history_requirement"),
        "dealer_participation_percentage": dealer_participation.get("percentage"),
        "dealer_participation_minimum": dealer_participation.get("minimum"),
        "dealer_participation_maximum": dealer_participation.get("maximum"),
        "dealer_participation_conditions": dealer_participation.get("conditions"),
        "chargeback_policy": participation.get("chargeback_policy"),
        "funding_method": funding.get("method"),
        "funding_contact_email": funding.get("contact_email"),
        "funding_contact_phone": funding.get("contact_phone"),
        "funding_hours": funding.get("hours"),
        "funding_address": funding.get("address"),
        "lien_holder_name": lien_holder.get("name"),
        "lien_holder_mailing_address": lien_holder.get("mailing_address"),
        "lien_holder_physical_address": lien_holder.get("physical_address"),
        "lien_holder_insurance_address": lien_holder.get("insurance_address"),
        "lien_holder_electronic_lien_code": lien_holder.get("electronic_lien_code"),
        "disclaimers": additional.get("disclaimers"),
        "rate_change_policy": additional.get("rate_change_policy"),
        "eligibility_notes": additional.get("eligibility_notes"),
        "other_comments": additional.get("other_comments")
    })

    row = result.fetchone()
    return row[0]


async def upsert_rate_policy_items(conn: AsyncConnection, bank_id: int, rate_sheet_data: dict) -> int:
    """
    Upsert rate_policy_items and return count.

    Args:
        conn: Database connection
        bank_id: Bank ID to upsert rate policy for
        rate_sheet_data: Complete rate sheet data dict

    Returns:
        Count of upserted rate policy items
    """
    rate_policy = rate_sheet_data.get("rate_policy") or {}
    count = 0

    query = text("""
        INSERT INTO rate_policy_items (
            bank_id, item_type, description, value, value_type, conditions, updated_at
        )
        VALUES (
            :bank_id, :item_type, :description, :value, :value_type, :conditions, NOW()
        )
        ON CONFLICT (bank_id, item_type, description) DO UPDATE SET
            value = EXCLUDED.value,
            value_type = EXCLUDED.value_type,
            conditions = EXCLUDED.conditions,
            updated_at = NOW()
    """)

    # Insert discounts
    for discount in rate_policy.get("available_discounts") or []:
        await conn.execute(query, {
            "bank_id": bank_id,
            "item_type": "discount",
            "description": discount.get("description"),
            "value": discount.get("value"),
            "value_type": discount.get("value_type"),
            "conditions": discount.get("conditions")
        })
        count += 1

    # Insert adjustments
    for adjustment in rate_policy.get("available_rate_adjustments") or []:
        await conn.execute(query, {
            "bank_id": bank_id,
            "item_type": "adjustment",
            "description": adjustment.get("description"),
            "value": adjustment.get("value"),
            "value_type": adjustment.get("value_type"),
            "conditions": adjustment.get("conditions")
        })
        count += 1

    # Insert fees
    for fee in rate_policy.get("fees") or []:
        await conn.execute(query, {
            "bank_id": bank_id,
            "item_type": "fee",
            "description": fee.get("description") or fee.get("type") or "Unspecified",
            "value": fee.get("value"),
            "value_type": fee.get("value_type"),
            "conditions": fee.get("description")
        })
        count += 1

    return count


async def upsert_loan_program_items(conn: AsyncConnection, bank_id: int, rate_sheet_data: dict) -> int:
    """
    Replace all loan_program_items for a bank and return total inserted count.

    Strategy: DELETE all existing rows for bank_id then INSERT fresh data.
    This avoids the PostgreSQL NULL != NULL unique-constraint issue that
    causes phantom duplicate rows when tier_name / term_in_months are NULL
    (as they are for 'program'-type rows).

    Args:
        conn: Database connection
        bank_id: Bank ID to replace loan programs for
        rate_sheet_data: Complete rate sheet data dict

    Returns:
        Count of inserted loan program items
    """
    loan_programs = rate_sheet_data.get("loan_programs") or []

    # Remove all existing rows for this bank before inserting fresh data
    await conn.execute(
        text("DELETE FROM loan_program_items WHERE bank_id = :bank_id"),
        {"bank_id": bank_id},
    )

    count = 0
    for program in loan_programs:
        program_id = await upsert_program(conn, bank_id, program)
        count += 1

        for tier in program.get("loan_tiers") or []:
            tier_id = await upsert_tier(conn, bank_id, program_id, program, tier)
            count += 1

            for term in tier.get("term_options") or []:
                await upsert_term(conn, bank_id, tier_id, program, tier, term)
                count += 1

    return count


async def upsert_program(conn: AsyncConnection, bank_id: int, program: dict) -> int:
    """
    Upsert a loan program and return its ID.

    Args:
        conn: Database connection
        bank_id: Bank ID
        program: Program data dict

    Returns:
        Loan program ID
    """
    ltv_details = program.get("ltv_details") or {}

    query = text("""
        INSERT INTO loan_program_items (
            bank_id, item_type, program_name, vehicle_type, model_year_range,
            min_model_year, max_model_year, mileage_limit,
            base_ltv, max_ltv, ltv_notes, updated_at
        )
        VALUES (
            :bank_id, 'program', :program_name, :vehicle_type, :model_year_range,
            :min_model_year, :max_model_year, :mileage_limit,
            :base_ltv, :max_ltv, :ltv_notes, NOW()
        )
        RETURNING loan_program_id
    """)

    result = await conn.execute(query, {
        "bank_id": bank_id,
        "program_name": program.get("program_name"),
        "vehicle_type": program.get("vehicle_type"),
        "model_year_range": program.get("model_year_range"),
        "min_model_year": program.get("min_model_year"),
        "max_model_year": program.get("max_model_year"),
        "mileage_limit": program.get("mileage_limit"),
        "base_ltv": ltv_details.get("base_ltv"),
        "max_ltv": ltv_details.get("max_ltv"),
        "ltv_notes": ltv_details.get("notes")
    })

    row = result.fetchone()
    return row[0]


async def upsert_tier(conn: AsyncConnection, bank_id: int, parent_id: int, program: dict, tier: dict) -> int:
    """
    Upsert a loan tier and return its ID. Includes parent program details.

    Args:
        conn: Database connection
        bank_id: Bank ID
        parent_id: Parent program ID
        program: Parent program data dict
        tier: Tier data dict

    Returns:
        Loan tier ID
    """
    ltv_details = program.get("ltv_details") or {}

    query = text("""
        INSERT INTO loan_program_items (
            bank_id, item_type, parent_id, program_name, tier_name,
            vehicle_type, model_year_range, min_model_year, max_model_year, mileage_limit,
            base_ltv, max_ltv, ltv_notes,
            credit_score_range, min_credit_score, max_credit_score, updated_at
        )
        VALUES (
            :bank_id, 'tier', :parent_id, :program_name, :tier_name,
            :vehicle_type, :model_year_range, :min_model_year, :max_model_year, :mileage_limit,
            :base_ltv, :max_ltv, :ltv_notes,
            :credit_score_range, :min_credit_score, :max_credit_score, NOW()
        )
        RETURNING loan_program_id
    """)

    result = await conn.execute(query, {
        "bank_id": bank_id,
        "parent_id": parent_id,
        "program_name": program.get("program_name"),
        "tier_name": tier.get("tier_name"),
        # Parent program details
        "vehicle_type": program.get("vehicle_type"),
        "model_year_range": program.get("model_year_range"),
        "min_model_year": program.get("min_model_year"),
        "max_model_year": program.get("max_model_year"),
        "mileage_limit": program.get("mileage_limit"),
        "base_ltv": ltv_details.get("base_ltv"),
        "max_ltv": ltv_details.get("max_ltv"),
        "ltv_notes": ltv_details.get("notes"),
        # Tier-specific details
        "credit_score_range": tier.get("credit_score_range"),
        "min_credit_score": tier.get("min_credit_score"),
        "max_credit_score": tier.get("max_credit_score")
    })

    row = result.fetchone()
    return row[0]


async def upsert_term(conn: AsyncConnection, bank_id: int, parent_id: int, program: dict, tier: dict, term: dict) -> None:
    """
    Upsert a loan term. Includes parent program and tier details.

    Args:
        conn: Database connection
        bank_id: Bank ID
        parent_id: Parent tier ID
        program: Parent program data dict
        tier: Parent tier data dict
        term: Term data dict
    """
    ltv_details = program.get("ltv_details") or {}

    query = text("""
        INSERT INTO loan_program_items (
            bank_id, item_type, parent_id, program_name, tier_name, term_in_months,
            vehicle_type, model_year_range, min_model_year, max_model_year, mileage_limit,
            base_ltv, max_ltv, ltv_notes,
            credit_score_range, min_credit_score, max_credit_score,
            min_loan_amount, max_loan_amount, rate, term_conditions, updated_at
        )
        VALUES (
            :bank_id, 'term', :parent_id, :program_name, :tier_name, :term_in_months,
            :vehicle_type, :model_year_range, :min_model_year, :max_model_year, :mileage_limit,
            :base_ltv, :max_ltv, :ltv_notes,
            :credit_score_range, :min_credit_score, :max_credit_score,
            :min_loan_amount, :max_loan_amount, :rate, :term_conditions, NOW()
        )
    """)

    await conn.execute(query, {
        "bank_id": bank_id,
        "parent_id": parent_id,
        "program_name": program.get("program_name"),
        "tier_name": tier.get("tier_name"),
        "term_in_months": term.get("term_in_months"),
        # Parent program details
        "vehicle_type": program.get("vehicle_type"),
        "model_year_range": program.get("model_year_range"),
        "min_model_year": program.get("min_model_year"),
        "max_model_year": program.get("max_model_year"),
        "mileage_limit": program.get("mileage_limit"),
        "base_ltv": ltv_details.get("base_ltv"),
        "max_ltv": ltv_details.get("max_ltv"),
        "ltv_notes": ltv_details.get("notes"),
        # Parent tier details
        "credit_score_range": tier.get("credit_score_range"),
        "min_credit_score": tier.get("min_credit_score"),
        "max_credit_score": tier.get("max_credit_score"),
        # Term-specific details
        "min_loan_amount": term.get("min_loan_amount"),
        "max_loan_amount": term.get("max_loan_amount"),
        "rate": term.get("rate"),
        "term_conditions": term.get("conditions")
    })
