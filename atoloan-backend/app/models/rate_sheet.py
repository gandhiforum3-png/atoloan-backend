"""
Pydantic v2 models for credit-union rate sheet structured data.
Used by both the LLM parser and the API response layer.
"""
from datetime import date
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


class Contact(BaseModel):
    phone: Optional[str] = Field(None, description="Primary contact phone number.")
    fax: Optional[str] = Field(None, description="Fax number for the credit union.")
    email: Optional[str] = Field(None, description="Contact email address.")
    website: Optional[str] = Field(None, description="Website URL of the credit union.")


class CreditUnionInfo(BaseModel):
    name: Optional[str] = Field(None, description="Full name of the credit union.")
    effective_date: Optional[date] = Field(None, description="Date when the rate sheet becomes effective.")
    replaces_rate_sheet_date: Optional[date] = Field(None, description="Date of the previous rate sheet replaced by this one.")
    address: Optional[str] = Field(None, description="Main address of the credit union.")
    contact: Optional[Contact] = Field(None, description="Contact details for the credit union.")
    contact_person: Optional[str] = Field(None, description="Name of the primary contact person or representative.")
    membership_eligibility: Optional[str] = Field(None, description="Eligibility criteria to become a credit union member.")
    branch_locations: Optional[List[str]] = Field(None, description="List of branch locations if applicable.")
    notes: Optional[str] = Field(None, description="Additional notes or information about the credit union.")
    maximum_debt_to_income_ratio: Optional[str] = Field(None, description="Maximum allowable debt-to-income ratio for loan applicants.")
    is_cosigner_allowed: Optional[bool] = Field(None, description="Indicates if cosigners are permitted on loans.")
    is_cosigner_same_address_required: Optional[bool] = Field(None, description="Indicates if cosigners must have the same address as the primary borrower.")
    cosigner_requirement_guidelines: Optional[List[str]] = Field(None, description="Guidelines for cosigner/borrower qualification requirements.")
    accept_out_region_loans: Optional[bool] = Field(None, description="Indicates if the credit union accepts loans for borrowers outside their region.")
    out_region_list: Optional[List[str]] = Field(None, description="List of county or states from which out-of-region loans are accepted.")
    is_credit_union_member_required: Optional[bool] = Field(None, description="Indicates if membership in the credit union is required to obtain a loan.")


class AvailableDiscount(BaseModel):
    description: Optional[str] = Field(None, description="Description of the discount or benefit offered or rate adjustment.")
    value: Optional[str] = Field(None, description="Numeric or percentage value of the discount.")
    value_type: Optional[str] = Field(None, description="Type of the value, e.g., 'percentage' or 'fixed amount'.")
    conditions: Optional[str] = Field(None, description="Conditions under which the discount or rate adjustment applies.")


class AvailableRateAdjustment(BaseModel):
    description: Optional[str] = Field(None, description="Description of the rate adjustment offered.")
    value: Optional[str] = Field(None, description="Numeric or percentage value of the rate adjustment.")
    value_type: Optional[str] = Field(None, description="Type of the value, e.g., 'percentage' or 'fixed amount'.")
    conditions: Optional[str] = Field(None, description="Conditions under which the rate adjustment applies.")


class Fee(BaseModel):
    type: Optional[str] = Field(None, description="Type or category of the fee (e.g., loan processing fee).")
    value: Optional[str] = Field(None, description="Monetary value or percentage amount of the fee.")
    value_type: Optional[str] = Field(None, description="Type of the value, e.g., 'percentage' or 'fixed amount'.")
    description: Optional[str] = Field(None, description="Additional details describing the fee.")


class RatePolicy(BaseModel):
    base_discount: Optional[str] = Field(None, description="General discount or base reduction applicable to rates.")
    available_discounts: Optional[List[AvailableDiscount]] = Field(None, description="List of available discounts and their conditions.")
    available_rate_adjustments: Optional[List[AvailableRateAdjustment]] = Field(None, description="List of available rate adjustments and their conditions.")
    fees: Optional[List[Fee]] = Field(None, description="List of fees applicable to the loan program.")
    donations_or_benefits: Optional[str] = Field(None, description="Any community donations or member benefits tied to the loan program.")

    @field_validator("fees", mode="before")
    @classmethod
    def coerce_fees(cls, v: Any) -> Any:
        if v is None:
            return v
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                result.append({"type": "Unspecified", "value": None, "description": item})
        return result


class TermOption(BaseModel):
    term_in_months: Optional[int] = Field(
        None,
        description="Loan term in months. For a range (e.g. '61-72'), use the upper value (72).",
    )
    min_loan_amount: Optional[int] = Field(None, description="Minimum loan amount in dollars.")
    max_loan_amount: Optional[int] = Field(None, description="Maximum loan amount in dollars.")
    rate: Optional[str] = Field(None, description="Interest rate as a percentage string, e.g. '5.25%'.")
    conditions: Optional[str] = Field(None, description="Conditions or notes applicable to this term.")


class LoanTier(BaseModel):
    tier_name: Optional[str] = Field(None, description="Tier label such as 'A+', 'A', 'B', etc.")
    credit_score_range: Optional[str] = Field(None, description="Credit score range for this tier. Max is 850.")
    min_credit_score: Optional[int] = Field(None, description="Minimum credit score for this tier.")
    max_credit_score: Optional[int] = Field(None, description="Maximum credit score for this tier (850 for the top tier).")
    term_options: Optional[List[TermOption]] = Field(None, description="List of loan terms available for this tier.")


class LTVDetails(BaseModel):
    base_ltv: Optional[str] = Field(None, description="Base loan-to-value percentage allowed.")
    max_ltv: Optional[str] = Field(None, description="Maximum allowable LTV percentage.")
    notes: Optional[str] = Field(None, description="Additional notes about the LTV policy.")


class LoanProgram(BaseModel):
    program_name: Optional[str] = Field(None, description="Name or category of the loan program.")
    vehicle_type: Optional[str] = Field(None, description="Type of vehicle financed (e.g. 'New', 'Used').")
    model_year_range: Optional[str] = Field(None, description="Range of model years (e.g. '>2023', '2014-2022').")
    min_model_year: Optional[int] = Field(None, description="Minimum model year allowed.")
    max_model_year: Optional[int] = Field(None, description="Maximum model year allowed.")
    mileage_limit: Optional[str] = Field(None, description="Maximum mileage allowed for eligible vehicles.")
    ltv_details: Optional[LTVDetails] = Field(None, description="Loan-to-value ratio information.")
    loan_tiers: Optional[List[LoanTier]] = Field(None, description="List of loan tiers defined by credit score.")


class Guidelines(BaseModel):
    income_requirements: Optional[str] = Field(None, description="Income criteria for loan eligibility.")
    debt_ratio_limits: Optional[str] = Field(None, description="Maximum allowable debt-to-income ratio, e.g. '45%'.")
    vehicle_restrictions: Optional[str] = Field(None, description="Restrictions on eligible vehicle types or conditions.")
    proof_of_income_rules: Optional[str] = Field(None, description="Rules related to proof of income documentation.")
    underwriting_rules: Optional[str] = Field(None, description="Underwriting guidelines or criteria.")
    credit_bureau_used: Optional[str] = Field(None, description="Credit bureau used for credit scoring.")
    documentation_required: Optional[List[str]] = Field(None, description="Required documents for loan application.")
    notes: Optional[str] = Field(None, description="Additional notes about underwriting or guidelines.")


class FirstTimeBuyer(BaseModel):
    is_first_time_buyer_participant: Optional[bool] = Field(None, description="Indicates participation in first-time buyer programs.")
    first_time_buyer_guideline: Optional[List[str]] = Field(None, description="Guidelines for first-time buyer program.")
    description: Optional[str] = Field(None, description="Overview of the first-time buyer program.")
    max_amount: Optional[str] = Field(None, description="Maximum loan amount under this program.")
    max_term: Optional[str] = Field(None, description="Maximum loan term (in months).")
    ltv: Optional[str] = Field(None, description="Maximum LTV ratio allowed.")
    fico_pricing: Optional[str] = Field(None, description="FICO-based pricing or minimum score requirements.")
    requirements: Optional[str] = Field(None, description="Eligibility requirements for first-time buyers.")


class SubPrime(BaseModel):
    description: Optional[str] = Field(None, description="Overview of the sub-prime loan program.")
    fico_limit: Optional[str] = Field(None, description="Maximum credit score for sub-prime qualification.")
    max_amount: Optional[str] = Field(None, description="Maximum loan amount for sub-prime applicants.")
    max_term: Optional[str] = Field(None, description="Maximum term for sub-prime loans.")
    ltv: Optional[str] = Field(None, description="Maximum LTV for sub-prime loans.")
    income_proof_required: Optional[str] = Field(None, description="Income proof requirements.")
    auto_history_requirement: Optional[str] = Field(None, description="Minimum required auto payment history.")


class SpecialPrograms(BaseModel):
    first_time_buyer: Optional[FirstTimeBuyer] = Field(None, description="First-time buyer program details.")
    sub_prime: Optional[SubPrime] = Field(None, description="Sub-prime lending program details.")


class DealerParticipation(BaseModel):
    percentage: Optional[str] = Field(None, description="Percentage of loan amount paid to dealer.")
    minimum: Optional[str] = Field(None, description="Minimum dealer participation amount.")
    maximum: Optional[str] = Field(None, description="Maximum dealer participation amount.")
    conditions: Optional[str] = Field(None, description="Conditions for dealer participation.")


class FundingInfo(BaseModel):
    method: Optional[str] = Field(None, description="Funding method (e.g. SmartFund, ACH).")
    contact_email: Optional[str] = Field(None, description="Email for funding inquiries.")
    contact_phone: Optional[str] = Field(None, description="Phone for funding support.")
    hours: Optional[str] = Field(None, description="Funding department working hours.")
    address: Optional[str] = Field(None, description="Address for funding correspondence.")


class LienHolderInfo(BaseModel):
    name: Optional[str] = Field(None, description="Lien holder's registered name.")
    mailing_address: Optional[str] = Field(None, description="Mailing address for lien documentation.")
    physical_address: Optional[str] = Field(None, description="Physical address.")
    insurance_address: Optional[str] = Field(None, description="Address for insurance documentation.")
    electronic_lien_code: Optional[str] = Field(None, description="Electronic lien code or identifier.")


class ParticipationAndFunding(BaseModel):
    dealer_participation: Optional[DealerParticipation] = Field(None, description="Dealer participation details.")
    chargeback_policy: Optional[str] = Field(None, description="Policy governing chargebacks.")
    funding: Optional[FundingInfo] = Field(None, description="Funding process details.")
    lien_holder_info: Optional[LienHolderInfo] = Field(None, description="Lien holder information.")


class AdditionalDetails(BaseModel):
    disclaimers: Optional[List[str]] = Field(None, description="Disclaimers or legal notes.")
    rate_change_policy: Optional[str] = Field(
        "Rates subject to change without prior notice.",
        description="Policy statement about rate changes.",
    )
    eligibility_notes: Optional[str] = Field(None, description="Additional eligibility notes.")
    other_comments: Optional[str] = Field(None, description="General comments not covered above.")

    @field_validator("eligibility_notes", "other_comments", mode="before")
    @classmethod
    def coerce_to_string(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        if isinstance(v, (list, tuple)):
            return "; ".join(str(item) for item in v if item)
        return str(v) if v else None


class CreditUnionRateSheet(BaseModel):
    credit_union_info: Optional[CreditUnionInfo] = Field(None, description="General information about the credit union.")
    rate_policy: Optional[RatePolicy] = Field(None, description="Rate policy including discounts and fees.")
    loan_programs: Optional[List[LoanProgram]] = Field(None, description="List of loan programs and rate tiers.")
    guidelines: Optional[Guidelines] = Field(None, description="Underwriting and eligibility guidelines.")
    special_programs: Optional[SpecialPrograms] = Field(None, description="Special loan programs.")
    participation_and_funding: Optional[ParticipationAndFunding] = Field(None, description="Dealer participation and funding details.")
    additional_details: Optional[AdditionalDetails] = Field(None, description="Miscellaneous details and disclaimers.")
