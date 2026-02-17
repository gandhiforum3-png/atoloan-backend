"""
Credit Union Retrieval Service
Handles all PostgreSQL SELECT/GET operations for credit unions, rate policies, and loan programs.
"""
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def get_all_credit_unions(conn: AsyncConnection) -> list[dict]:
    """
    Retrieve all credit unions from database.

    Args:
        conn: Database connection

    Returns:
        List of credit unions with id and name
    """
    query = text("""
        SELECT bank_id, name FROM bank_info
        ORDER BY name
    """)

    result = await conn.execute(query)
    rows = result.fetchall()

    return [
        {
            "id": row[0],
            "name": row[1]
        }
        for row in rows
    ]


async def get_bank_info(conn: AsyncConnection, bank_id: int) -> dict | None:
    """
    Retrieve bank info and structure it into comprehensive format.

    Args:
        conn: Database connection
        bank_id: Bank ID to retrieve

    Returns:
        Structured bank info dict or None if not found
    """
    query = text("""
        SELECT * FROM bank_info WHERE bank_id = :bank_id
    """)

    result = await conn.execute(query, {"bank_id": bank_id})
    row = result.fetchone()

    if not row:
        return None

    # Convert row to dict
    row_dict = dict(row._mapping)

    # Structure the response
    return {
        "credit_union_info": {
            "name": row_dict.get("name"),
            "effective_date": row_dict.get("effective_date"),
            "replaces_rate_sheet_date": row_dict.get("replaces_rate_sheet_date"),
            "address": row_dict.get("address"),
            "contact": {
                "phone": row_dict.get("contact_phone"),
                "fax": row_dict.get("contact_fax"),
                "email": row_dict.get("contact_email"),
                "website": row_dict.get("contact_website")
            },
            "contact_person": row_dict.get("contact_person"),
            "membership_eligibility": row_dict.get("membership_eligibility"),
            "branch_locations": row_dict.get("branch_locations"),
            "notes": row_dict.get("notes"),
            "maximum_debt_to_income_ratio": row_dict.get("maximum_debt_to_income_ratio"),
            "is_cosigner_allowed": row_dict.get("is_cosigner_allowed"),
            "is_cosigner_same_address_required": row_dict.get("is_cosigner_same_address_required"),
            "cosigner_requirement_guidelines": row_dict.get("cosigner_requirement_guidelines"),
            "accept_out_region_loans": row_dict.get("accept_out_region_loans"),
            "out_region_list": row_dict.get("out_region_list"),
            "is_credit_union_member_required": row_dict.get("is_credit_union_member_required")
        },
        "guidelines": {
            "income_requirements": None,
            "debt_ratio_limits": row_dict.get("maximum_debt_to_income_ratio"),
            "vehicle_restrictions": None,
            "proof_of_income_rules": None,
            "underwriting_rules": None,
            "credit_bureau_used": None,
            "documentation_required": None,
            "notes": row_dict.get("notes")
        },
        "special_programs": {
            "first_time_buyer": {
                "is_first_time_buyer_participant": row_dict.get("ftd_is_participant"),
                "first_time_buyer_guideline": row_dict.get("ftd_guidelines"),
                "description": row_dict.get("ftd_description"),
                "max_amount": row_dict.get("ftd_max_amount"),
                "max_term": row_dict.get("ftd_max_term"),
                "ltv": row_dict.get("ftd_ltv"),
                "fico_pricing": row_dict.get("ftd_fico_pricing"),
                "requirements": row_dict.get("ftd_requirements")
            },
            "sub_prime": {
                "description": row_dict.get("subprime_description"),
                "fico_limit": row_dict.get("subprime_fico_limit"),
                "max_amount": row_dict.get("subprime_max_amount"),
                "max_term": row_dict.get("subprime_max_term"),
                "ltv": row_dict.get("subprime_ltv"),
                "income_proof_required": row_dict.get("subprime_income_proof_required"),
                "auto_history_requirement": row_dict.get("subprime_auto_history_requirement")
            } if row_dict.get("subprime_description") else None
        },
        "participation_and_funding": {
            "dealer_participation": {
                "percentage": row_dict.get("dealer_participation_percentage"),
                "minimum": row_dict.get("dealer_participation_minimum"),
                "maximum": row_dict.get("dealer_participation_maximum"),
                "conditions": row_dict.get("dealer_participation_conditions")
            },
            "chargeback_policy": row_dict.get("chargeback_policy"),
            "funding": {
                "method": row_dict.get("funding_method"),
                "contact_email": row_dict.get("funding_contact_email"),
                "contact_phone": row_dict.get("funding_contact_phone"),
                "hours": row_dict.get("funding_hours"),
                "address": row_dict.get("funding_address")
            },
            "lien_holder_info": {
                "name": row_dict.get("lien_holder_name"),
                "mailing_address": row_dict.get("lien_holder_mailing_address"),
                "physical_address": row_dict.get("lien_holder_physical_address"),
                "insurance_address": row_dict.get("lien_holder_insurance_address"),
                "electronic_lien_code": row_dict.get("lien_holder_electronic_lien_code")
            }
        },
        "additional_details": {
            "disclaimers": row_dict.get("disclaimers"),
            "rate_change_policy": row_dict.get("rate_change_policy"),
            "eligibility_notes": row_dict.get("eligibility_notes"),
            "other_comments": row_dict.get("other_comments")
        }
    }


async def get_rate_policy(conn: AsyncConnection, bank_id: int) -> dict:
    """
    Retrieve rate policy items from database.

    Args:
        conn: Database connection
        bank_id: Bank ID to retrieve rate policy for

    Returns:
        Structured rate policy dict with discounts, adjustments, and fees
    """
    query = text("""
        SELECT * FROM rate_policy_items
        WHERE bank_id = :bank_id
        ORDER BY item_type, description
    """)

    result = await conn.execute(query, {"bank_id": bank_id})
    rows = result.fetchall()

    discounts = []
    adjustments = []
    fees = []

    for row in rows:
        row_dict = dict(row._mapping)
        item = {
            "description": row_dict.get("description"),
            "value": row_dict.get("value"),
            "value_type": row_dict.get("value_type"),
            "conditions": row_dict.get("conditions")
        }

        if row_dict.get("item_type") == "discount":
            discounts.append(item)
        elif row_dict.get("item_type") == "adjustment":
            adjustments.append(item)
        elif row_dict.get("item_type") == "fee":
            fees.append(item)

    return {
        "base_discount": None,
        "available_discounts": discounts if discounts else None,
        "available_rate_adjustments": adjustments if adjustments else None,
        "fees": fees if fees else None,
        "donations_or_benefits": None
    }


async def get_loan_programs(conn: AsyncConnection, bank_id: int) -> list[dict]:
    """
    Retrieve loan programs with hierarchical structure (programs → tiers → terms).

    Args:
        conn: Database connection
        bank_id: Bank ID to retrieve loan programs for

    Returns:
        List of loan programs with nested tiers and terms
    """
    # Get all loan program items
    query = text("""
        SELECT * FROM loan_program_items
        WHERE bank_id = :bank_id
        ORDER BY program_name, item_type, tier_name, term_in_months
    """)

    result = await conn.execute(query, {"bank_id": bank_id})
    rows = result.fetchall()

    # Organize into hierarchical structure
    programs_dict = {}

    for row in rows:
        row_dict = dict(row._mapping)
        item_type = row_dict.get("item_type")
        program_name = row_dict.get("program_name")

        # Initialize program if not exists
        if program_name not in programs_dict:
            programs_dict[program_name] = {
                "program_name": program_name,
                "vehicle_type": None,
                "model_year_range": None,
                "min_model_year": None,
                "max_model_year": None,
                "mileage_limit": None,
                "ltv_details": {},
                "loan_tiers": {}
            }

        program = programs_dict[program_name]

        if item_type == "program":
            # Update program-level details
            program["vehicle_type"] = row_dict.get("vehicle_type")
            program["model_year_range"] = row_dict.get("model_year_range")
            program["min_model_year"] = row_dict.get("min_model_year")
            program["max_model_year"] = row_dict.get("max_model_year")
            program["mileage_limit"] = row_dict.get("mileage_limit")
            program["ltv_details"] = {
                "base_ltv": row_dict.get("base_ltv"),
                "max_ltv": row_dict.get("max_ltv"),
                "notes": row_dict.get("ltv_notes")
            }

        elif item_type == "tier":
            tier_name = row_dict.get("tier_name")
            if tier_name not in program["loan_tiers"]:
                program["loan_tiers"][tier_name] = {
                    "tier_name": tier_name,
                    "credit_score_range": row_dict.get("credit_score_range"),
                    "min_credit_score": row_dict.get("min_credit_score"),
                    "max_credit_score": row_dict.get("max_credit_score"),
                    "term_options": []
                }

        elif item_type == "term":
            tier_name = row_dict.get("tier_name")
            # Ensure tier exists
            if tier_name not in program["loan_tiers"]:
                program["loan_tiers"][tier_name] = {
                    "tier_name": tier_name,
                    "credit_score_range": row_dict.get("credit_score_range"),
                    "min_credit_score": row_dict.get("min_credit_score"),
                    "max_credit_score": row_dict.get("max_credit_score"),
                    "term_options": []
                }

            program["loan_tiers"][tier_name]["term_options"].append({
                "term_in_months": row_dict.get("term_in_months"),
                "min_loan_amount": row_dict.get("min_loan_amount"),
                "max_loan_amount": row_dict.get("max_loan_amount"),
                "rate": row_dict.get("rate"),
                "conditions": row_dict.get("term_conditions")
            })

    # Convert to list format
    programs_list = []
    for program in programs_dict.values():
        # Convert tiers dict to list
        program["loan_tiers"] = list(program["loan_tiers"].values())
        programs_list.append(program)

    return programs_list
