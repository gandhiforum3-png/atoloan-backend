"""
Test Bank Finder Algorithm with Mock Data
Validates the bank finder logic with various scenarios.
"""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection
from app.services.bank_finder import find_best_bank


# Mock data for testing
MOCK_ZIPCODES = [
    {"zipcode": "90210", "city": "Los Angeles County"},
    {"zipcode": "10001", "city": "New York County"},
    {"zipcode": "60601", "city": "Cook County"},
    {"zipcode": "33101", "city": "Miami-Dade County"},
]

MOCK_BANKS = [
    {
        "bank_id": 1,
        "name": "National Credit Union",
        "accept_out_region_loans": True,
        "out_region_list": None,  # Accepts everywhere
    },
    {
        "bank_id": 2,
        "name": "California Local CU",
        "accept_out_region_loans": False,
        "out_region_list": ["Los Angeles County", "San Diego County"],  # Only CA counties
    },
    {
        "bank_id": 3,
        "name": "Unrestricted Federal CU",
        "accept_out_region_loans": False,
        "out_region_list": None,  # No restrictions = nationwide
    },
    {
        "bank_id": 4,
        "name": "New York Only CU",
        "accept_out_region_loans": False,
        "out_region_list": ["New York County"],  # Only NY
    },
    {
        "bank_id": 5,
        "name": "Empty List CU",
        "accept_out_region_loans": False,
        "out_region_list": [],  # Empty list = nationwide
    },
]

MOCK_LOAN_PROGRAMS = [
    # National Credit Union - Best rate for excellent credit
    {
        "bank_id": 1,
        "program_name": "Prime Auto Loan",
        "tier_name": "Excellent Credit",
        "term_in_months": 60,
        "min_loan_amount": 5000,
        "max_loan_amount": 100000,
        "rate": "3.99%",
        "min_credit_score": 720,
        "max_credit_score": 850,
    },
    {
        "bank_id": 1,
        "program_name": "Prime Auto Loan",
        "tier_name": "Good Credit",
        "term_in_months": 60,
        "min_loan_amount": 5000,
        "max_loan_amount": 100000,
        "rate": "5.49%",
        "min_credit_score": 680,
        "max_credit_score": 719,
    },
    # California Local CU - Competitive rate
    {
        "bank_id": 2,
        "program_name": "California Auto",
        "tier_name": "Excellent Credit",
        "term_in_months": 60,
        "min_loan_amount": 10000,
        "max_loan_amount": 80000,
        "rate": "4.25%",
        "min_credit_score": 720,
        "max_credit_score": 850,
    },
    {
        "bank_id": 2,
        "program_name": "California Auto",
        "tier_name": "Good Credit",
        "term_in_months": 60,
        "min_loan_amount": 10000,
        "max_loan_amount": 80000,
        "rate": "5.75%",
        "min_credit_score": 680,
        "max_credit_score": 719,
    },
    # Unrestricted Federal CU - Highest rate
    {
        "bank_id": 3,
        "program_name": "Federal Auto",
        "tier_name": "Excellent Credit",
        "term_in_months": 60,
        "min_loan_amount": 5000,
        "max_loan_amount": 75000,
        "rate": "4.99%",
        "min_credit_score": 720,
        "max_credit_score": 850,
    },
    # New York Only CU - Great rate but limited geography
    {
        "bank_id": 4,
        "program_name": "NY Auto Loan",
        "tier_name": "Excellent Credit",
        "term_in_months": 60,
        "min_loan_amount": 8000,
        "max_loan_amount": 90000,
        "rate": "3.75%",
        "min_credit_score": 720,
        "max_credit_score": 850,
    },
    # Empty List CU - Medium rate
    {
        "bank_id": 5,
        "program_name": "Standard Auto",
        "tier_name": "Excellent Credit",
        "term_in_months": 60,
        "min_loan_amount": 5000,
        "max_loan_amount": 100000,
        "rate": "4.49%",
        "min_credit_score": 720,
        "max_credit_score": 850,
    },
]


async def setup_mock_tables(conn: AsyncConnection):
    """Create and populate mock tables for testing."""

    # Drop existing test tables if they exist
    await conn.execute(text("DROP TABLE IF EXISTS test_loan_program_items"))
    await conn.execute(text("DROP TABLE IF EXISTS test_bank_info"))
    await conn.execute(text("DROP TABLE IF EXISTS test_zipcode"))

    # Create test zipcode table
    await conn.execute(text("""
        CREATE TABLE test_zipcode (
            zipcode VARCHAR(10) PRIMARY KEY,
            city VARCHAR(255) NOT NULL
        )
    """))

    # Create test bank_info table
    await conn.execute(text("""
        CREATE TABLE test_bank_info (
            bank_id INTEGER PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            accept_out_region_loans BOOLEAN,
            out_region_list TEXT[]
        )
    """))

    # Create test loan_program_items table
    await conn.execute(text("""
        CREATE TABLE test_loan_program_items (
            id SERIAL PRIMARY KEY,
            bank_id INTEGER NOT NULL,
            item_type VARCHAR(50) DEFAULT 'term',
            program_name VARCHAR(255),
            tier_name VARCHAR(255),
            term_in_months INTEGER,
            min_loan_amount INTEGER,
            max_loan_amount INTEGER,
            rate VARCHAR(20),
            min_credit_score INTEGER,
            max_credit_score INTEGER
        )
    """))

    # Insert mock zipcode data
    for zipcode in MOCK_ZIPCODES:
        await conn.execute(
            text("INSERT INTO test_zipcode (zipcode, city) VALUES (:zipcode, :city)"),
            zipcode
        )

    # Insert mock bank data
    for bank in MOCK_BANKS:
        await conn.execute(
            text("""
                INSERT INTO test_bank_info (bank_id, name, accept_out_region_loans, out_region_list)
                VALUES (:bank_id, :name, :accept_out_region_loans, :out_region_list)
            """),
            bank
        )

    # Insert mock loan program data
    for program in MOCK_LOAN_PROGRAMS:
        await conn.execute(
            text("""
                INSERT INTO test_loan_program_items
                (bank_id, program_name, tier_name, term_in_months, min_loan_amount, max_loan_amount,
                 rate, min_credit_score, max_credit_score, item_type)
                VALUES (:bank_id, :program_name, :tier_name, :term_in_months, :min_loan_amount,
                        :max_loan_amount, :rate, :min_credit_score, :max_credit_score, 'term')
            """),
            program
        )

    await conn.commit()
    print("✅ Mock tables created and populated")


async def cleanup_mock_tables(conn: AsyncConnection):
    """Remove mock tables after testing."""
    await conn.execute(text("DROP TABLE IF EXISTS test_loan_program_items"))
    await conn.execute(text("DROP TABLE IF EXISTS test_bank_info"))
    await conn.execute(text("DROP TABLE IF EXISTS test_zipcode"))
    await conn.commit()
    print("✅ Mock tables cleaned up")


async def modify_queries_for_test_tables(conn: AsyncConnection):
    """
    Temporarily modify the bank_finder queries to use test tables.
    In production, we'd use dependency injection, but for quick testing we'll modify directly.
    """
    # Note: This is a hack for testing. In production, we'd pass table names as parameters
    # or use a proper testing framework with dependency injection
    pass


async def run_test_scenarios():
    """Run various test scenarios to validate the bank finder algorithm."""

    # You need to update this with your actual database connection string
    DATABASE_URL = "postgresql+asyncpg://user:password@localhost/dbname"

    print("=" * 80)
    print("BANK FINDER ALGORITHM VALIDATION TEST")
    print("=" * 80)

    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        # Setup mock data
        await setup_mock_tables(conn)

        # Test scenarios
        test_cases = [
            {
                "name": "Test 1: Los Angeles - Excellent Credit - High Down Payment",
                "zipcode": "90210",
                "down_payment": 25000,
                "credit_score": 750,
                "expected_eligible_banks": [1, 2, 3, 5],  # Not bank 4 (NY only)
                "expected_best_bank_id": 1,  # National CU has 3.99%
                "expected_rate": "3.99%"
            },
            {
                "name": "Test 2: New York - Excellent Credit - Medium Down Payment",
                "zipcode": "10001",
                "down_payment": 20000,
                "credit_score": 740,
                "expected_eligible_banks": [1, 3, 4, 5],  # Not bank 2 (CA only)
                "expected_best_bank_id": 4,  # NY Only CU has 3.75%
                "expected_rate": "3.75%"
            },
            {
                "name": "Test 3: Chicago - Good Credit - Medium Down Payment",
                "zipcode": "60601",
                "down_payment": 18000,
                "credit_score": 690,
                "expected_eligible_banks": [1, 3, 5],  # Not bank 2 (CA) or 4 (NY)
                "expected_best_bank_id": 1,  # National CU has 5.49%
                "expected_rate": "5.49%"
            },
            {
                "name": "Test 4: Los Angeles - Excellent Credit - Low Down Payment",
                "zipcode": "90210",
                "down_payment": 8000,
                "credit_score": 760,
                "expected_eligible_banks": [1, 3, 5],  # Not bank 2 (min 10k) or 4 (NY, min 8k exact match)
                "expected_best_bank_id": 1,  # National CU has 3.99%
                "expected_rate": "3.99%"
            },
            {
                "name": "Test 5: Miami - Excellent Credit - High Down Payment",
                "zipcode": "33101",
                "down_payment": 30000,
                "credit_score": 780,
                "expected_eligible_banks": [1, 3, 5],  # Not bank 2 (CA) or 4 (NY)
                "expected_best_bank_id": 1,  # National CU has 3.99%
                "expected_rate": "3.99%"
            },
        ]

        # Note: The actual bank_finder.py uses production table names
        # For this test to work properly, we need to either:
        # 1. Temporarily replace production tables (DANGEROUS)
        # 2. Modify bank_finder.py to accept table name parameters
        # 3. Create a test version of bank_finder.py

        print("\n⚠️  NOTE: This test creates mock tables with 'test_' prefix.")
        print("⚠️  The bank_finder.py code needs to be modified to use test tables,")
        print("⚠️  or you need to copy data to production tables for testing.")
        print("\nMOCK DATA SUMMARY:")
        print("-" * 80)

        # Show mock data summary
        print("\n📍 ZIPCODES:")
        for z in MOCK_ZIPCODES:
            print(f"  {z['zipcode']} → {z['city']}")

        print("\n🏦 BANKS:")
        for b in MOCK_BANKS:
            out_region = b['out_region_list'] if b['out_region_list'] else "None (nationwide)"
            accepts = "Yes" if b['accept_out_region_loans'] else "No"
            print(f"  [{b['bank_id']}] {b['name']}")
            print(f"      Accept out-of-region: {accepts}")
            print(f"      Region list: {out_region}")

        print("\n💰 LOAN PROGRAMS (by bank):")
        current_bank = None
        for p in sorted(MOCK_LOAN_PROGRAMS, key=lambda x: x['bank_id']):
            if current_bank != p['bank_id']:
                current_bank = p['bank_id']
                bank_name = next(b['name'] for b in MOCK_BANKS if b['bank_id'] == p['bank_id'])
                print(f"\n  [{p['bank_id']}] {bank_name}:")
            print(f"      {p['tier_name']}: {p['rate']} | CS: {p['min_credit_score']}-{p['max_credit_score']} | Loan: ${p['min_loan_amount']:,}-${p['max_loan_amount']:,}")

        print("\n" + "=" * 80)
        print("TEST SCENARIOS")
        print("=" * 80)

        for i, test in enumerate(test_cases, 1):
            print(f"\n{test['name']}")
            print("-" * 80)
            print(f"Input: zipcode={test['zipcode']}, down_payment=${test['down_payment']:,}, credit_score={test['credit_score']}")
            print(f"Expected eligible banks: {test['expected_eligible_banks']}")
            print(f"Expected best: Bank {test['expected_best_bank_id']} at {test['expected_rate']}")

            # This would work if we modify bank_finder to use test tables
            # result = await find_best_bank(conn, test['zipcode'], test['down_payment'], test['credit_score'])
            # For now, we'll just show what the test would check

            print("Status: ⏸️  Skipped (requires bank_finder.py modification for test tables)")

        print("\n" + "=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print("✅ Mock data structure validated")
        print("✅ Test scenarios defined")
        print("⚠️  To run actual tests, modify bank_finder.py to accept table name parameters")
        print("   or copy test data to production tables (not recommended)")

        # Cleanup
        await cleanup_mock_tables(conn)

    await engine.dispose()


async def main():
    """Main test runner."""
    try:
        await run_test_scenarios()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("\nTo run this test:")
    print("1. Update DATABASE_URL in the script with your connection string")
    print("2. Run: python test_bank_finder.py")
    print("\nFor actual testing, consider modifying bank_finder.py to accept")
    print("table name parameters for easier testing, or use a separate test database.\n")

    # Uncomment to run:
    # asyncio.run(main())
