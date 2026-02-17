"""
Example script demonstrating how to use the /parse-rate-sheet-markdown endpoint.

This script shows:
1. How to call the endpoint with markdown content
2. How to handle success and error responses
3. How to work with the returned structured data
"""

import json
import requests
from typing import Optional, Dict, Any

# Configuration
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
    payload = {
        "markdown_text": markdown_text,
        "current_year": current_year
    }
    
    try:
        response = requests.post(ENDPOINT, json=payload, timeout=120)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("status") == "success":
            return data.get("result")
        else:
            print(f"Parsing failed: {data.get('error')}")
            return None
            
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to {ENDPOINT}")
        print("Make sure the backend is running: uvicorn app.main:app --reload")
        return None
    except requests.exceptions.Timeout:
        print("Error: Request timed out. The markdown may be very large.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None


def print_rate_sheet_summary(rate_sheet: Dict[str, Any]) -> None:
    """Pretty-print a summary of the parsed rate sheet."""
    
    print("\n" + "="*80)
    print("RATE SHEET PARSING RESULTS")
    print("="*80)
    
    # Credit Union Info
    cu_info = rate_sheet.get("credit_union_info", {})
    if cu_info:
        print(f"\n📍 CREDIT UNION INFORMATION")
        print(f"   Name: {cu_info.get('name', 'N/A')}")
        print(f"   Effective Date: {cu_info.get('effective_date', 'N/A')}")
        print(f"   Address: {cu_info.get('address', 'N/A')}")
        if cu_info.get('contact'):
            contact = cu_info['contact']
            print(f"   Contact: {contact.get('phone', 'N/A')} | {contact.get('email', 'N/A')}")
    
    # Rate Policy
    rate_policy = rate_sheet.get("rate_policy", {})
    if rate_policy:
        print(f"\n💰 RATE POLICY")
        print(f"   Base Discount: {rate_policy.get('base_discount', 'N/A')}")
        
        discounts = rate_policy.get('available_discounts', [])
        if discounts:
            print(f"   Available Discounts:")
            for discount in discounts[:3]:  # Show first 3
                print(f"      - {discount.get('description')}: {discount.get('value')} {discount.get('value_type')}")
            if len(discounts) > 3:
                print(f"      ... and {len(discounts) - 3} more")
    
    # Loan Programs
    loan_programs = rate_sheet.get("loan_programs", [])
    if loan_programs:
        print(f"\n🚗 LOAN PROGRAMS ({len(loan_programs)} programs found)")
        for program in loan_programs[:3]:  # Show first 3
            print(f"   • {program.get('program_name', 'N/A')}")
            print(f"     Vehicle Type: {program.get('vehicle_type', 'N/A')}")
            print(f"     Model Year Range: {program.get('model_year_range', 'N/A')}")
            
            tiers = program.get('tiers', [])
            if tiers:
                print(f"     Credit Tiers: {', '.join([t.get('tier_name', 'N/A') for t in tiers])}")
        
        if len(loan_programs) > 3:
            print(f"   ... and {len(loan_programs) - 3} more programs")
    
    # Guidelines
    guidelines = rate_sheet.get("guidelines", {})
    if guidelines:
        print(f"\n📋 GUIDELINES")
        if guidelines.get('income_requirements'):
            print(f"   Income Requirements: {guidelines.get('income_requirements')}")
        if guidelines.get('debt_ratio_limits'):
            print(f"   Debt Ratio Limits: {guidelines.get('debt_ratio_limits')}")
        if guidelines.get('credit_bureau_used'):
            print(f"   Credit Bureau: {guidelines.get('credit_bureau_used')}")
    
    # Special Programs
    special_programs = rate_sheet.get("special_programs", {})
    if special_programs:
        print(f"\n🎯 SPECIAL PROGRAMS")
        ftb = special_programs.get('first_time_buyer')
        if ftb and ftb.get('is_first_time_buyer_participant'):
            print(f"   ✓ First Time Buyer Program Available")
        sp = special_programs.get('sub_prime')
        if sp and sp.get('description'):
            print(f"   ✓ Sub-Prime Program Available")
    
    print("\n" + "="*80 + "\n")


def example_markdown():
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
3. **Membership Length Discount**: 0.10% off for members of 5+ years
4. **EV Discount**: 0.25% off for electric vehicles

## Loan Programs

### New Auto - Less than 2 Years Old

#### Platinum Tier (740+ FICO)
| Term | Min Amount | Max Amount | Rate |
|------|-----------|-----------|------|
| 36 months | $5,000 | $75,000 | 4.99% |
| 48 months | $5,000 | $75,000 | 5.24% |
| 60 months | $5,000 | $75,000 | 5.49% |
| 72 months | $5,000 | $75,000 | 5.99% |

#### Gold Tier (700-739 FICO)
| Term | Min Amount | Max Amount | Rate |
|------|-----------|-----------|------|
| 36 months | $5,000 | $75,000 | 5.49% |
| 48 months | $5,000 | $75,000 | 5.74% |
| 60 months | $5,000 | $75,000 | 5.99% |
| 72 months | $5,000 | $75,000 | 6.49% |

### Used Auto - 3-6 Years Old (2019-2022)

#### Platinum Tier (740+ FICO)
| Term | Min Amount | Max Amount | Rate |
|------|-----------|-----------|------|
| 36 months | $5,000 | $65,000 | 5.99% |
| 48 months | $5,000 | $65,000 | 6.24% |
| 60 months | $5,000 | $65,000 | 6.49% |

## Guidelines

### Income Requirements
- Minimum annual income of $25,000
- Income verification required

### Debt-to-Income Limits
- Maximum 45% DTI for all applicants
- Maximum 50% DTI for first-time buyers with co-signer

### Vehicle Restrictions
- No salvage titles
- No flood titles
- No branded titles
- No commercial vehicles
- Maximum mileage: 200,000 miles

### Credit Bureau
- Experian FICO 8 score used for underwriting

### Documentation Required
- Valid driver's license
- Social Security card
- Proof of income (paystub or tax return)
- Proof of insurance
- Proof of residence (utility bill)

## Special Programs

### First-Time Buyer Program
- Available for buyers with 0 previous auto loans
- Maximum loan amount: $45,000
- Maximum term: 72 months
- Special FICO pricing available for scores 650+

### Re-Start Program
- Available for borrowers with bankruptcy discharged 24+ months ago
- Maximum loan amount: $35,000
- FICO requirement: 550+
- Co-signer recommended but not required

## Participation & Funding

### Dealer Participation
- **Flat Commission**: 2% of loan amount
- **Minimum Payout**: $300
- **Maximum Payout**: $2,500
- ACH funding available within 24 hours

### Funding Method
- ACH preferred
- Contact: funding@example.cu
- Hours: Monday-Friday 8am-5pm EST

## Additional Information

### Disclosures
- Rates subject to change without notice
- Loans subject to credit approval
- All terms estimated and subject to verification

### Rate Change Policy
- Rates may be adjusted quarterly based on market conditions
- Members will be notified of any rate changes
"""


if __name__ == "__main__":
    # Example 1: Parse the sample markdown
    print("Parsing example rate sheet markdown...")
    markdown = example_markdown()
    
    rate_sheet = parse_rate_sheet_markdown(markdown)
    
    if rate_sheet:
        print_rate_sheet_summary(rate_sheet)
        
        # Example 2: Access specific data
        print("\n" + "="*80)
        print("ACCESSING SPECIFIC DATA")
        print("="*80)
        
        cu_name = rate_sheet.get("credit_union_info", {}).get("name")
        print(f"Credit Union Name: {cu_name}")
        
        num_programs = len(rate_sheet.get("loan_programs", []))
        print(f"Number of Loan Programs: {num_programs}")
        
        # Example 3: Iterate through loan programs
        print("\n" + "="*80)
        print("LOAN PROGRAM DETAILS")
        print("="*80)
        
        for program in rate_sheet.get("loan_programs", [])[:2]:
            print(f"\nProgram: {program.get('program_name')}")
            for tier in program.get('tiers', [])[:1]:
                print(f"  Tier: {tier.get('tier_name')}")
                print(f"  Credit Score Range: {tier.get('credit_score_range')}")
                for term in tier.get('term_options', [])[:2]:
                    print(f"    - {term.get('term_in_months')} months: {term.get('rate')}")
    else:
        print("Failed to parse rate sheet")
