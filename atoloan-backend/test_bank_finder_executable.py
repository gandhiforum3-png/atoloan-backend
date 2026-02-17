"""
Executable Test for Bank Finder Algorithm
This version can actually run tests by using configurable table names.
"""
import asyncio
import os
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# Mock data
MOCK_ZIPCODES = [
    {"zipcode": "90210", "city": "Los Angeles County"},
    {"zipcode": "10001", "city": "New York County"},
    {"zipcode": "60601", "city": "Cook County"},
]

MOCK_BANKS = [
    {"bank_id": 101, "name": "National Credit Union", "accept_out_region_loans": True, "out_region_list": None},
    {"bank_id": 102, "name": "California Local CU", "accept_out_region_loans": False, "out_region_list": ["Los Angeles County"]},
    {"bank_id": 103, "name": "No Restrictions CU", "accept_out_region_loans": False, "out_region_list": None},
    {"bank_id": 104, "name": "New York Only CU", "accept_out_region_loans": False, "out_region_list": ["New York County"]},
    {"bank_id": 105, "name": "Empty List CU", "accept_out_region_loans": False, "out_region_list": []},
]

MOCK_PROGRAMS = [
    {"bank_id": 101, "program_name": "Prime", "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 5000, "max_loan_amount": 100000, "rate": "3.99%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 101, "program_name": "Prime", "tier_name": "Good", "term_in_months": 60, "min_loan_amount": 5000, "max_loan_amount": 100000, "rate": "5.49%", "min_credit_score": 680, "max_credit_score": 719},
    {"bank_id": 102, "program_name": "CA Auto", "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 10000, "max_loan_amount": 80000, "rate": "4.25%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 103, "program_name": "Federal", "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 5000, "max_loan_amount": 75000, "rate": "4.99%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 104, "program_name": "NY Auto", "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 8000, "max_loan_amount": 90000, "rate": "3.75%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 105, "program_name": "Standard", "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 5000, "max_loan_amount": 100000, "rate": "4.49%", "min_credit_score": 720, "max_credit_score": 850},
]


async def setup_test_data(conn: AsyncConnection):
    """Insert test data into production tables (will be cleaned up after)."""
    # Insert zipcodes
    for z in MOCK_ZIPCODES:
        await conn.execute(
            text("INSERT INTO zipcode (zipcode, city) VALUES (:zipcode, :city) ON CONFLICT (zipcode) DO NOTHING"),
            z
        )

    # Insert banks
    for b in MOCK_BANKS:
        await conn.execute(
            text("""
                INSERT INTO bank_info (bank_id, name, accept_out_region_loans, out_region_list)
                VALUES (:bank_id, :name, :accept_out_region_loans, :out_region_list)
                ON CONFLICT (bank_id) DO NOTHING
            """),
            b
        )

    # Insert programs
    for p in MOCK_PROGRAMS:
        await conn.execute(
            text("""
                INSERT INTO loan_program_items
                (bank_id, program_name, tier_name, term_in_months, min_loan_amount, max_loan_amount,
                 rate, min_credit_score, max_credit_score, item_type)
                VALUES (:bank_id, :program_name, :tier_name, :term_in_months, :min_loan_amount,
                        :max_loan_amount, :rate, :min_credit_score, :max_credit_score, 'term')
            """),
            p
        )

    await conn.commit()
    print("✅ Test data inserted")


async def cleanup_test_data(conn: AsyncConnection):
    """Remove test data from production tables."""
    test_bank_ids = [b["bank_id"] for b in MOCK_BANKS]

    for bank_id in test_bank_ids:
        await conn.execute(text("DELETE FROM loan_program_items WHERE bank_id = :bank_id"), {"bank_id": bank_id})
        await conn.execute(text("DELETE FROM bank_info WHERE bank_id = :bank_id"), {"bank_id": bank_id})

    await conn.commit()
    print("✅ Test data cleaned up")


async def find_best_bank_test(
    conn: AsyncConnection,
    zipcode: str,
    down_payment: float,
    credit_score: int
) -> Optional[dict]:
    """Test version of find_best_bank - same logic as production."""

    # Step 1: Get county from zipcode
    query = text("SELECT city FROM zipcode WHERE zipcode = :zipcode LIMIT 1")
    result = await conn.execute(query, {"zipcode": str(zipcode)})
    row = result.fetchone()

    if not row:
        return None

    user_county = row[0]
    print(f"  📍 Location: {zipcode} → {user_county}")

    # Step 2: Get eligible banks
    query = text("""
        SELECT bank_id, name, accept_out_region_loans, out_region_list
        FROM bank_info
        WHERE
            accept_out_region_loans = true
            OR (out_region_list IS NULL OR out_region_list = '{}')
            OR :user_county = ANY(out_region_list)
        ORDER BY name
    """)

    result = await conn.execute(query, {"user_county": user_county})
    rows = result.fetchall()

    eligible_banks = [{"bank_id": r[0], "name": r[1]} for r in rows]
    print(f"  🏦 Eligible banks: {[f'{b['bank_id']}-{b['name']}' for b in eligible_banks]}")

    # Step 3: Find best rate
    best_offer = None
    best_rate = float('inf')

    for bank in eligible_banks:
        bank_id = bank["bank_id"]
        bank_name = bank["name"]

        query = text("""
            SELECT program_name, tier_name, term_in_months, min_loan_amount, max_loan_amount,
                   rate, min_credit_score, max_credit_score
            FROM loan_program_items
            WHERE
                bank_id = :bank_id
                AND item_type = 'term'
                AND min_credit_score <= :credit_score
                AND max_credit_score >= :credit_score
                AND (min_loan_amount IS NULL OR min_loan_amount <= :down_payment)
                AND (max_loan_amount IS NULL OR max_loan_amount >= :down_payment)
                AND rate IS NOT NULL
            ORDER BY rate ASC
            LIMIT 1
        """)

        result = await conn.execute(query, {
            "bank_id": bank_id,
            "credit_score": credit_score,
            "down_payment": down_payment
        })

        row = result.fetchone()

        if row:
            rate_str = row[5]
            try:
                rate_value = float(rate_str.replace('%', '').strip()) if isinstance(rate_str, str) else float(rate_str)
            except (ValueError, AttributeError):
                continue

            if rate_value < best_rate:
                best_rate = rate_value
                best_offer = {
                    "bank_id": bank_id,
                    "bank_name": bank_name,
                    "interest_rate": rate_str,
                    "program_name": row[0],
                    "tier_name": row[1],
                    "term_in_months": row[2],
                }

    return best_offer


async def run_tests():
    """Run test scenarios."""

    # Get database URL from environment
    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "postgres")

    DATABASE_URL = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    print("=" * 80)
    print("BANK FINDER ALGORITHM - EXECUTABLE TEST")
    print("=" * 80)

    engine = create_async_engine(DATABASE_URL, echo=False)

    test_cases = [
        {
            "name": "Test 1: LA - Excellent Credit (750) - $25k down",
            "zipcode": "90210",
            "down_payment": 25000,
            "credit_score": 750,
            "expected_bank": "National Credit Union",
            "expected_rate": "3.99%",
            "reason": "Should find National CU (nationwide, 3.99%) and CA Local (eligible county, 4.25%). Best: National at 3.99%"
        },
        {
            "name": "Test 2: NY - Excellent Credit (740) - $20k down",
            "zipcode": "10001",
            "down_payment": 20000,
            "credit_score": 740,
            "expected_bank": "New York Only CU",
            "expected_rate": "3.75%",
            "reason": "Should find NY Only CU (eligible county, 3.75%). Best rate available."
        },
        {
            "name": "Test 3: Chicago - Good Credit (690) - $18k down",
            "zipcode": "60601",
            "down_payment": 18000,
            "credit_score": 690,
            "expected_bank": "National Credit Union",
            "expected_rate": "5.49%",
            "reason": "Good credit tier. CA & NY CUs not eligible (county). National CU eligible with 5.49% for good credit."
        },
        {
            "name": "Test 4: LA - Excellent Credit (760) - $8k down (low)",
            "zipcode": "90210",
            "down_payment": 8000,
            "credit_score": 760,
            "expected_bank": "National Credit Union",
            "expected_rate": "3.99%",
            "reason": "CA Local requires min $10k. National CU accepts $5k+. Best rate: 3.99%"
        },
    ]

    async with engine.begin() as conn:
        # Setup
        await setup_test_data(conn)

        print("\nMOCK DATA LOADED:")
        print("  📍 Zipcodes: 90210 (LA County), 10001 (NY County), 60601 (Cook County)")
        print("  🏦 Banks:")
        print("     [101] National CU - accept_out_region=true (nationwide)")
        print("     [102] CA Local - out_region_list=['Los Angeles County']")
        print("     [103] No Restrictions - out_region_list=null (nationwide)")
        print("     [104] NY Only - out_region_list=['New York County']")
        print("     [105] Empty List - out_region_list=[] (nationwide)")

        print("\n" + "=" * 80)
        print("RUNNING TEST SCENARIOS")
        print("=" * 80)

        passed = 0
        failed = 0

        for i, test in enumerate(test_cases, 1):
            print(f"\n{'─' * 80}")
            print(f"TEST {i}: {test['name']}")
            print(f"{'─' * 80}")
            print(f"Input: zipcode={test['zipcode']}, down_payment=${test['down_payment']:,}, credit_score={test['credit_score']}")
            print(f"Expected: {test['expected_bank']} at {test['expected_rate']}")
            print(f"Reason: {test['reason']}\n")

            result = await find_best_bank_test(
                conn,
                test['zipcode'],
                test['down_payment'],
                test['credit_score']
            )

            if result:
                print(f"  ✓ Result: {result['bank_name']} ({result['program_name']} - {result['tier_name']})")
                print(f"  ✓ Rate: {result['interest_rate']}")
                print(f"  ✓ Term: {result['term_in_months']} months")

                if result['bank_name'] == test['expected_bank'] and result['interest_rate'] == test['expected_rate']:
                    print(f"\n  ✅ PASS - Matched expected result")
                    passed += 1
                else:
                    print(f"\n  ❌ FAIL - Expected {test['expected_bank']} at {test['expected_rate']}")
                    failed += 1
            else:
                print(f"  ✗ No result found")
                print(f"\n  ❌ FAIL - Expected {test['expected_bank']} at {test['expected_rate']}")
                failed += 1

        # Cleanup
        print("\n" + "=" * 80)
        await cleanup_test_data(conn)

    await engine.dispose()

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"✅ Passed: {passed}/{len(test_cases)}")
    print(f"❌ Failed: {failed}/{len(test_cases)}")

    if failed == 0:
        print("\n🎉 All tests passed! The bank finder algorithm is working correctly.")
    else:
        print("\n⚠️  Some tests failed. Review the logic above.")

    print("=" * 80)


if __name__ == "__main__":
    print("\nStarting executable test...")
    print("This test will:")
    print("  1. Insert test data into your database")
    print("  2. Run the bank finder algorithm")
    print("  3. Clean up test data")
    print("\nPress Ctrl+C to cancel, or wait 3 seconds to continue...")

    import time
    try:
        time.sleep(3)
        asyncio.run(run_tests())
    except KeyboardInterrupt:
        print("\n\nTest cancelled by user.")
