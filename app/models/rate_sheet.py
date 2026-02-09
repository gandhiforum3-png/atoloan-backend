from typing import List, Optional
from pydantic.v1 import validator
from datetime import date
try:
    # Prefer pydantic v1 compatibility layer when pydantic v2 is installed
    from pydantic.v1 import BaseModel, Field
except Exception:
    # Fallback to importing directly (pydantic v1)
    from pydantic import BaseModel, Field


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

    @validator("fees", pre=True, always=True)
    def coerce_fees(cls, v):
        if v is None:
            return v
        new_list = []
        for item in v:
            if isinstance(item, dict):
                new_list.append(item)
            elif isinstance(item, str):
                # Auto-wrap string fee entries into Fee objects
                new_list.append({"type": "Unspecified", "amount": None, "description": item})
        return new_list

class TermOption(BaseModel):
    term_in_months: Optional[int] = Field(None, description="Loan terms are defined in months if Range of months is given, select upper value of range as term (e.g., '0-36' select 36, '61-72' select 72).") 
    min_loan_amount: Optional[int] = Field(None, description="Minimum loan amount allowed for this term. amount should be in dollars.")
    max_loan_amount: Optional[int] = Field(None, description="Maximum loan amount allowed for this term. amount should be in dollars.")
    rate: Optional[str] = Field(None, description="Standard interest rate for this term shown in percentage format, e.g., '5.25%'.")
    conditions: Optional[str] = Field(None, description="Conditions or notes applicable to this term.")


class LoanTier(BaseModel):
    tier_name: Optional[str] = Field(None, description="Tier label such as 'A+', 'A', 'B', etc.")
    credit_score_range: Optional[str] = Field(None, description="Credit score range corresponding to this tier. max score should be 850")
    min_credit_score: Optional[int] = Field(None, description="Minimum credit score for this tier.")
    max_credit_score: Optional[int] = Field(None, description="Maximum credit score for this tier (should be 850 for the highest tier).")
    term_options: Optional[List[TermOption]] = Field(None, description="List of loan terms available for this tier.")


class LTVDetails(BaseModel):
    base_ltv: Optional[str] = Field(None, description="Base loan-to-value (LTV) percentage allowed.")
    max_ltv: Optional[str] = Field(None, description="Maximum allowable LTV percentage.")
    notes: Optional[str] = Field(None, description="Additional notes about the LTV policy.")


class LoanProgram(BaseModel):
    program_name: Optional[str] = Field(None, description="Name or category of the loan program (e.g., 'Auto Loan', 'Used Vehicle').")
    vehicle_type: Optional[str] = Field(None, description="Type of vehicle or asset financed under the program.")
    model_year_range: Optional[str] = Field(None, description="Range of model years applicable to this loan type.example values are >2023 or 2014-2022")
    min_model_year: Optional[int] = Field(None, description="Minimum model year allowed for the loan. if model_year_range is '>2023', min_model_year should be 2024. if > 2 years use current year minus 2. if 2023-2025 then min_model_year is 2023.")
    max_model_year: Optional[int] = Field(None, description="Maximum model year allowed for the loan. if model_year_range is '>2023', max_model_year should be 2023. if > 2 years use current year. if 2023-2025 then max_model_year is 2025.")
    mileage_limit: Optional[str] = Field(None, description="Maximum mileage allowed for eligible vehicles.")
    ltv_details: Optional[LTVDetails] = Field(None, description="Loan-to-value ratio information for the program.")
    loan_tiers: Optional[List[LoanTier]] = Field(None, description="List of loan tiers defined by credit score or risk category.")


class Guidelines(BaseModel):
    income_requirements: Optional[str] = Field(None, description="Income criteria or requirements for loan eligibility.")
    debt_ratio_limits: Optional[str] = Field(None, description="Maximum allowable debt-to-income ratio. it should be in prcentage format, e.g., '45%'.")
    vehicle_restrictions: Optional[str] = Field(None, description="Restrictions on eligible vehicle types or conditions.")
    proof_of_income_rules: Optional[str] = Field(None, description="Rules related to proof of income documentation.")
    underwriting_rules: Optional[str] = Field(None, description="Underwriting guidelines or criteria.")
    credit_bureau_used: Optional[str] = Field(None, description="Credit bureau used for credit scoring.")
    documentation_required: Optional[List[str]] = Field(None, description="List of required documents for loan application.")
    notes: Optional[str] = Field(None, description="Additional notes about underwriting or guidelines.")


class FirstTimeBuyer(BaseModel):
    is_first_time_buyer_participant: Optional[bool] = Field(None, description="Indicates if the credit union participates in first-time buyer programs.")
    first_time_buyer_guideline: Optional[List[str]] = Field(None, description="Guidelines for first-time buyer program participation.")
    description: Optional[str] = Field(None, description="Overview of first-time buyer program.")
    max_amount: Optional[str] = Field(None, description="Maximum loan amount allowed under this program.")
    max_term: Optional[str] = Field(None, description="Maximum loan term (in months) for first-time buyers.")
    ltv: Optional[str] = Field(None, description="Maximum loan-to-value ratio allowed.")
    fico_pricing: Optional[str] = Field(None, description="Applicable FICO-based pricing or minimum score requirements.")
    requirements: Optional[str] = Field(None, description="Eligibility requirements for first-time buyers.")


class SubPrime(BaseModel):
    description: Optional[str] = Field(None, description="Overview of sub-prime loan program.")
    fico_limit: Optional[str] = Field(None, description="Maximum credit score for sub-prime qualification.")
    max_amount: Optional[str] = Field(None, description="Maximum loan amount for sub-prime applicants.")
    max_term: Optional[str] = Field(None, description="Maximum term for sub-prime loans.")
    ltv: Optional[str] = Field(None, description="Maximum loan-to-value ratio for sub-prime loans.")
    income_proof_required: Optional[str] = Field(None, description="Income proof requirements for sub-prime applicants.")
    auto_history_requirement: Optional[str] = Field(None, description="Minimum required auto payment history.")


class SpecialPrograms(BaseModel):
    first_time_buyer: Optional[FirstTimeBuyer] = Field(None, description="Details of the first-time buyer program, if available.")
    sub_prime: Optional[SubPrime] = Field(None, description="Details of the sub-prime lending program, if available.")


class DealerParticipation(BaseModel):
    percentage: Optional[str] = Field(None, description="Percentage of loan amount paid to dealer as participation.")
    minimum: Optional[str] = Field(None, description="Minimum dealer participation amount.")
    maximum: Optional[str] = Field(None, description="Maximum dealer participation amount.")
    conditions: Optional[str] = Field(None, description="Conditions under which dealer participation applies.")


class FundingInfo(BaseModel):
    method: Optional[str] = Field(None, description="Funding method (e.g., SmartFund, ACH, etc.).")
    contact_email: Optional[str] = Field(None, description="Email for funding-related inquiries.")
    contact_phone: Optional[str] = Field(None, description="Phone number for funding support.")
    hours: Optional[str] = Field(None, description="Funding department working hours.")
    address: Optional[str] = Field(None, description="Mailing or physical address for funding-related correspondence.")


class LienHolderInfo(BaseModel):
    name: Optional[str] = Field(None, description="Lien holder’s registered name.")
    mailing_address: Optional[str] = Field(None, description="Mailing address for lien documentation.")
    physical_address: Optional[str] = Field(None, description="Physical address for lien correspondence.")
    insurance_address: Optional[str] = Field(None, description="Address for insurance documentation.")
    electronic_lien_code: Optional[str] = Field(None, description="Electronic lien code or identifier used for processing.")


class ParticipationAndFunding(BaseModel):
    dealer_participation: Optional[DealerParticipation] = Field(None, description="Dealer participation payment details.")
    chargeback_policy: Optional[str] = Field(None, description="Policy governing chargebacks on early-paid or defaulted loans.")
    funding: Optional[FundingInfo] = Field(None, description="Funding process details including contact info and methods.")
    lien_holder_info: Optional[LienHolderInfo] = Field(None, description="Lien holder information including addresses and codes.")


class AdditionalDetails(BaseModel):
    disclaimers: Optional[List[str]] = Field(None, description="List of disclaimers or legal notes.")
    rate_change_policy: Optional[str] = Field("Rates subject to change without prior notice.", description="Policy statement about rate changes.")
    eligibility_notes: Optional[str] = Field(None, description="Additional eligibility notes or restrictions.")
    other_comments: Optional[str] = Field(None, description="Any other general comments or details not covered above.")

    @validator("eligibility_notes", "other_comments", pre=True, always=False)
    def coerce_to_string(cls, v):
        """Coerce list or other types to string."""
        if v is None:
            return None
        if isinstance(v, str):
            return v
        if isinstance(v, (list, tuple)):
            # join list items into a single string
            return "; ".join(str(item) for item in v if item)
        # Convert other types to string
        return str(v) if v else None


class CreditUnionRateSheet(BaseModel):
    credit_union_info: Optional[CreditUnionInfo] = Field(None, description="General information about the credit union.")
    rate_policy: Optional[RatePolicy] = Field(None, description="Rate policy including discounts and fees.")
    loan_programs: Optional[List[LoanProgram]] = Field(None, description="List of loan programs and rate tiers.")
    guidelines: Optional[Guidelines] = Field(None, description="Underwriting and eligibility guidelines.")
    special_programs: Optional[SpecialPrograms] = Field(None, description="Special loan programs such as first-time buyer or sub-prime.")
    participation_and_funding: Optional[ParticipationAndFunding] = Field(None, description="Dealer participation and funding details.")
    additional_details: Optional[AdditionalDetails] = Field(None, description="Miscellaneous details, disclaimers, and notes.")
