"""
Example script demonstrating how to use the /parse-rate-sheet-markdown endpoint.

Run the backend first:
    cd atoloan-backend/atoloan-backend
    uvicorn app.main:app --reload

Then in a separate shell:
    python scripts/example_parse_rate_sheet.py
"""

import json
import requests
from typing import Any, Dict, Optional

API_BASE_URL = "http://localhost:8000"
ENDPOINT = f"{API_BASE_URL}/parse-rate-sheet-markdown"


def parse_rate_sheet_markdown(markdown_text: str, current_year: int = 2025) -> Optional[Dict[str, Any]]:
    """
    Call the /parse-rate-sheet-markdown endpoint.

    Args:
        markdown_text: The markdown content from a rate sheet
        current_year: The year to use for model year calculations (default: 2025)

    Returns:
        The parsed rate sheet data or None if parsing failed
    """
    payload = {"markdown_text": markdown_text, "current_year": current_year}

    try:
        response = requests.post(ENDPOINT, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            return data.get("result")
        print(f"Parsing failed: {data.get('error')}")
        return None
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to {ENDPOINT}")
        print("Make sure the backend is running: uvicorn app.main:app --reload")
        return None
    except requests.exceptions.Timeout:
        print("Error: Request timed out. The markdown may be very large.")
        return None
    except requests.exceptions.RequestException as exc:
        print(f"Error: {exc}")
        return None


def print_rate_sheet_summary(rate_sheet: Dict[str, Any]) -> None:
    """Pretty-print a summary of the parsed rate sheet."""
    print("\n" + "=" * 80)
    print("RATE SHEET PARSING RESULTS")
    print("=" * 80)

    cu_info = rate_sheet.get("credit_union_info", {})
    if cu_info:
        print(f"\n📍 CREDIT UNION INFORMATION")
        print(f"   Name: {cu_info.get('name', 'N/A')}")
        print(f"   Effective Date: {cu_info.get('effective_date', 'N/A')}")
        print(f"   Address: {cu_info.get('address', 'N/A')}")
        if cu_info.get("contact"):
            contact = cu_info["contact"]
            print(f"   Contact: {contact.get('phone', 'N/A')} | {contact.get('email', 'N/A')}")

    rate_policy = rate_sheet.get("rate_policy", {})
    if rate_policy:
        print(f"\n💰 RATE POLICY")
        print(f"   Base Discount: {rate_policy.get('base_discount', 'N/A')}")
        discounts = rate_policy.get("available_discounts", [])
        if discounts:
            print(f"   Available Discounts:")
            for discount in discounts[:3]:
                print(f"      - {discount.get('description')}: {discount.get('value')} {discount.get('value_type')}")
            if len(discounts) > 3:
                print(f"      ... and {len(discounts) - 3} more")

    loan_programs = rate_sheet.get("loan_programs", [])
    if loan_programs:
        print(f"\n🚗 LOAN PROGRAMS ({len(loan_programs)} programs found)")
        for program in loan_programs[:3]:
            print(f"   • {program.get('program_name', 'N/A')}")
            print(f"     Vehicle Type: {program.get('vehicle_type', 'N/A')}")
            print(f"     Model Year Range: {program.get('model_year_range', 'N/A')}")
            tiers = program.get("tiers", [])
            if tiers:
                print(f"     Credit Tiers: {', '.join([t.get('tier_name', 'N/A') for t in tiers])}")
        if len(loan_programs) > 3:
            print(f"   ... and {len(loan_programs) - 3} more programs")

    guidelines = rate_sheet.get("guidelines", {})
    if guidelines:
        print(f"\n📋 GUIDELINES")
        if guidelines.get("income_requirements"):
            print(f"   Income Requirements: {guidelines.get('income_requirements')}")
        if guidelines.get("debt_ratio_limits"):
            print(f"   Debt Ratio Limits: {guidelines.get('debt_ratio_limits')}")
        if guidelines.get("credit_bureau_used"):
            print(f"   Credit Bureau: {guidelines.get('credit_bureau_used')}")

    special_programs = rate_sheet.get("special_programs", {})
    if special_programs:
        print(f"\n🎯 SPECIAL PROGRAMS")
        ftb = special_programs.get("first_time_buyer")
        if ftb and ftb.get("is_first_time_buyer_participant"):
            print(f"   ✓ First Time Buyer Program Available")
        sp = special_programs.get("sub_prime")
        if sp and sp.get("description"):
            print(f"   ✓ Sub-Prime Program Available")

    print("\n" + "=" * 80 + "\n")


def example_markdown() -> str:
    """Return an example rate sheet markdown for testing."""
    return """
# Example Credit Union Rate Sheet

## Credit Union Information
- **Name**: Example Credit Union
- **Effective Date**: January 1, 2025
- **Address**: 123 Main Street, Anytown, USA 12345
- **Phone**: (555) 123-4567
- **Email**: info@example.cu
- **Website**: www.example.cu

## Rate Policy

### Base Discount
- 4.99% floor rate for qualified members

### Available Discounts
1. **Autopay Discount**: 0.25% off when enrolled in automatic payments
2. **Direct Deposit Discount**: 0.125% off with direct deposit
3. **EV Discount**: 0.25% off for electric vehicles

## Loan Programs

### New Auto - Less than 2 Years Old

#### Platinum Tier (740+ FICO)
| Term | Min Amount | Max Amount | Rate |
|------|-----------|-----------|------|
| 36 months | $5,000 | $75,000 | 4.99% |
| 60 months | $5,000 | $75,000 | 5.49% |
| 72 months | $5,000 | $75,000 | 5.99% |

## Guidelines

### Income Requirements
- Minimum annual income of $25,000

### Debt-to-Income Limits
- Maximum 45% DTI for all applicants

## Special Programs

### First-Time Buyer Program
- Available for buyers with 0 previous auto loans
- Maximum loan amount: $45,000

## Participation & Funding

### Dealer Participation
- **Flat Commission**: 2% of loan amount
- ACH funding available within 24 hours
"""


if __name__ == "__main__":
    print("Parsing example rate sheet markdown...")
    markdown = example_markdown()

    rate_sheet = parse_rate_sheet_markdown(markdown)

    if rate_sheet:
        print_rate_sheet_summary(rate_sheet)

        cu_name = rate_sheet.get("credit_union_info", {}).get("name")
        print(f"Credit Union Name: {cu_name}")

        num_programs = len(rate_sheet.get("loan_programs", []))
        print(f"Number of Loan Programs: {num_programs}")
    else:
        print("Failed to parse rate sheet")
