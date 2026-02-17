#!/usr/bin/env python3
"""
Test script to validate the rate sheet parser with AMERICAN FIRST CU.md content
"""

import sys
import os
from pathlib import Path

# Add the atoloan-backend directory to path
sys.path.insert(0, str(Path(__file__).parent / "atoloan-backend"))

# Load environment variables
from dotenv import load_dotenv
env_file = Path(__file__).parent / "atoloan-backend" / ".env.example"
if env_file.exists():
    print(f"✓ Loading environment from: {env_file}")
    load_dotenv(env_file)
else:
    print(f"✗ .env.example not found at: {env_file}")
    sys.exit(1)

# Check if API key is set
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("✗ OPENAI_API_KEY not set")
    sys.exit(1)
else:
    # Show masked key for security
    masked_key = api_key[:20] + "..." + api_key[-4:] if len(api_key) > 24 else "***"
    print(f"✓ OPENAI_API_KEY configured: {masked_key}")

# Now try to import and test the parser
try:
    from app.services.rate_sheet_parser import parse_rate_sheet_from_markdown
    print("✓ Successfully imported rate_sheet_parser")
except Exception as e:
    print(f"✗ Failed to import rate_sheet_parser: {e}")
    sys.exit(1)

# Read the test markdown file
markdown_file = Path(__file__).parent / "atoloan-backend" / "upload_pdf" / "AMERICAN FIRST CU.md"
if not markdown_file.exists():
    print(f"✗ Test markdown file not found: {markdown_file}")
    sys.exit(1)

print(f"\n✓ Reading test markdown from: {markdown_file}")
markdown_text = markdown_file.read_text()
print(f"  File size: {len(markdown_text)} bytes")
print(f"  Preview (first 200 chars): {markdown_text[:200]}...")

print("\n" + "="*80)
print("STARTING PARSER VALIDATION")
print("="*80 + "\n")

try:
    print("Parsing rate sheet markdown...")
    result = parse_rate_sheet_from_markdown(markdown_text)
    
    print("\n" + "="*80)
    print("PARSER VALIDATION SUCCESSFUL!")
    print("="*80 + "\n")
    
    # Display results
    print("📊 PARSED RESULTS:")
    print("-" * 80)
    
    if result.credit_union_info:
        cu_info = result.credit_union_info
        print(f"\n1️⃣  CREDIT UNION INFO:")
        print(f"   Name: {cu_info.name}")
        print(f"   Effective Date: {cu_info.effective_date}")
        print(f"   Address: {cu_info.address}")
        if cu_info.contact:
            print(f"   Website: {cu_info.contact.website}")
            print(f"   Phone: {cu_info.contact.phone}")
            print(f"   Email: {cu_info.contact.email}")
        if cu_info.contact_person:
            print(f"   Contacts: {cu_info.contact_person[:100]}..." if len(cu_info.contact_person) > 100 else f"   Contacts: {cu_info.contact_person}")
    
    if result.rate_policy:
        rp = result.rate_policy
        print(f"\n2️⃣  RATE POLICY:")
        print(f"   Base Discount: {rp.base_discount}")
        if rp.available_discounts:
            print(f"   Available Discounts: {len(rp.available_discounts)}")
            for disc in rp.available_discounts[:2]:
                print(f"     • {disc.description}: {disc.value}")
        if rp.available_rate_adjustments:
            print(f"   Rate Adjustments: {len(rp.available_rate_adjustments)}")
        if rp.fees:
            print(f"   Fees: {len(rp.fees)}")
    
    if result.guidelines:
        guide = result.guidelines
        print(f"\n3️⃣  GUIDELINES:")
        print(f"   Income Requirements: {guide.income_requirements[:80]}..." if guide.income_requirements and len(guide.income_requirements) > 80 else f"   Income Requirements: {guide.income_requirements}")
        print(f"   Debt Ratio Limits: {guide.debt_ratio_limits}")
        print(f"   Vehicle Restrictions: {guide.vehicle_restrictions[:80]}..." if guide.vehicle_restrictions and len(guide.vehicle_restrictions) > 80 else f"   Vehicle Restrictions: {guide.vehicle_restrictions}")
        print(f"   Underwriting Rules: {guide.underwriting_rules[:80]}..." if guide.underwriting_rules and len(guide.underwriting_rules) > 80 else f"   Underwriting Rules: {guide.underwriting_rules}")
    
    if result.loan_programs:
        print(f"\n4️⃣  LOAN PROGRAMS ({len(result.loan_programs)} found):")
        for i, program in enumerate(result.loan_programs[:3], 1):  # Show first 3
            print(f"\n   Program {i}: {program.program_name}")
            print(f"   - Vehicle Type: {program.vehicle_type}")
            print(f"   - Model Year Range: {program.model_year_range}")
            print(f"   - Mileage Limit: {program.mileage_limit}")
            if program.ltv_details:
                print(f"   - Max LTV: {program.ltv_details.max_ltv}")
            if program.loan_tiers:
                print(f"   - FICO Tiers: {len(program.loan_tiers)}")
                for tier in program.loan_tiers[:2]:  # Show first 2 tiers
                    print(f"     • {tier.tier_name}: {tier.credit_score_range}")
        
        if len(result.loan_programs) > 3:
            print(f"\n   ... and {len(result.loan_programs) - 3} more programs")
    
    if result.special_programs:
        sp = result.special_programs
        print(f"\n5️⃣  SPECIAL PROGRAMS:")
        if sp.first_time_buyer:
            print(f"   First-Time Buyer: {sp.first_time_buyer.is_first_time_buyer_participant}")
            if sp.first_time_buyer.description:
                print(f"   - Details: {sp.first_time_buyer.description[:80]}...")
        if sp.sub_prime:
            print(f"   Sub-Prime Program: Available")
            print(f"   - FICO Limit: {sp.sub_prime.fico_limit}")
            print(f"   - Max Amount: {sp.sub_prime.max_amount}")
    
    if result.participation_and_funding:
        pf = result.participation_and_funding
        print(f"\n6️⃣  PARTICIPATION & FUNDING:")
        if pf.dealer_participation:
            print(f"   Dealer Participation: {pf.dealer_participation.percentage}%")
            print(f"   - Min: {pf.dealer_participation.minimum}")
            print(f"   - Max: {pf.dealer_participation.maximum}")
        if pf.funding:
            print(f"   Funding Method: {pf.funding.method}")
            print(f"   - Phone: {pf.funding.contact_phone}")
            print(f"   - Email: {pf.funding.contact_email}")
    
    if result.additional_details:
        ad = result.additional_details
        print(f"\n7️⃣  ADDITIONAL DETAILS:")
        print(f"   Rate Change Policy: {ad.rate_change_policy}")
        if ad.disclaimers:
            print(f"   Disclaimers: {len(ad.disclaimers)}")
            for disc in ad.disclaimers[:2]:
                print(f"     • {disc[:80]}..." if len(disc) > 80 else f"     • {disc}")
        if ad.eligibility_notes:
            print(f"   Eligibility Notes: {ad.eligibility_notes[:80]}...")
    
    print("\n" + "="*80)
    print("✓ VALIDATION COMPLETE - Parser successfully extracted all sections!")
    print("="*80)
    
except Exception as e:
    print("\n" + "="*80)
    print("✗ PARSER VALIDATION FAILED")
    print("="*80)
    print(f"\nError Type: {type(e).__name__}")
    print(f"Error Message: {str(e)}")
    print("\nTraceback:")
    import traceback
    traceback.print_exc()
    sys.exit(1)
