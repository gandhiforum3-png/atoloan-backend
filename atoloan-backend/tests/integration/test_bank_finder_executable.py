"""
Executable integration test for the Bank Finder algorithm.

Inserts mock data into the real database, runs find_best_bank, and cleans up.
Skipped when no DB connection is available.

Usage:
    cd atoloan-backend/atoloan-backend
    pytest tests/integration/test_bank_finder_executable.py -v -s
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Mock data (bank IDs in 100+ range to avoid collisions with real data)
# ---------------------------------------------------------------------------

MOCK_ZIPCODES = [
    {"zipcode": "90210", "city": "Los Angeles County"},
    {"zipcode": "10001", "city": "New York County"},
    {"zipcode": "60601", "city": "Cook County"},
]

MOCK_BANKS = [
    {"bank_id": 101, "name": "National Credit Union",   "accept_out_region_loans": True,  "out_region_list": None},
    {"bank_id": 102, "name": "California Local CU",     "accept_out_region_loans": False, "out_region_list": ["Los Angeles County"]},
    {"bank_id": 103, "name": "No Restrictions CU",      "accept_out_region_loans": False, "out_region_list": None},
    {"bank_id": 104, "name": "New York Only CU",        "accept_out_region_loans": False, "out_region_list": ["New York County"]},
    {"bank_id": 105, "name": "Empty List CU",           "accept_out_region_loans": False, "out_region_list": []},
]

MOCK_PROGRAMS = [
    {"bank_id": 101, "program_name": "Prime",    "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 5000,  "max_loan_amount": 100000, "rate": "3.99%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 101, "program_name": "Prime",    "tier_name": "Good",      "term_in_months": 60, "min_loan_amount": 5000,  "max_loan_amount": 100000, "rate": "5.49%", "min_credit_score": 680, "max_credit_score": 719},
    {"bank_id": 102, "program_name": "CA Auto",  "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 10000, "max_loan_amount": 80000,  "rate": "4.25%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 103, "program_name": "Federal",  "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 5000,  "max_loan_amount": 75000,  "rate": "4.99%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 104, "program_name": "NY Auto",  "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 8000,  "max_loan_amount": 90000,  "rate": "3.75%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 105, "program_name": "Standard", "tier_name": "Excellent", "term_in_months": 60, "min_loan_amount": 5000,  "max_loan_amount": 100000, "rate": "4.49%", "min_credit_score": 720, "max_credit_score": 850},
]

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _setup(conn: AsyncConnection) -> None:
    # Clean up any data left by a previous aborted run before inserting fresh data
    await _teardown(conn)
    for z in MOCK_ZIPCODES:
        await conn.execute(
            text("INSERT INTO zipcode (zipcode, city) VALUES (:zipcode, :city) ON CONFLICT (zipcode) DO NOTHING"),
            z,
        )
    for b in MOCK_BANKS:
        await conn.execute(
            text("""
                INSERT INTO bank_info (bank_id, name, accept_out_region_loans, out_region_list)
                VALUES (:bank_id, :name, :accept_out_region_loans, :out_region_list)
                ON CONFLICT (bank_id) DO NOTHING
            """),
            b,
        )
    for p in MOCK_PROGRAMS:
        await conn.execute(
            text("""
                INSERT INTO loan_program_items
                    (bank_id, program_name, tier_name, term_in_months,
                     min_loan_amount, max_loan_amount, rate,
                     min_credit_score, max_credit_score, item_type)
                VALUES
                    (:bank_id, :program_name, :tier_name, :term_in_months,
                     :min_loan_amount, :max_loan_amount, :rate,
                     :min_credit_score, :max_credit_score, 'term')
            """),
            p,
        )


async def _teardown(conn: AsyncConnection) -> None:
    test_ids = [b["bank_id"] for b in MOCK_BANKS]
    for bid in test_ids:
        await conn.execute(text("DELETE FROM loan_program_items WHERE bank_id = :b"), {"b": bid})
        await conn.execute(text("DELETE FROM bank_info WHERE bank_id = :b"), {"b": bid})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _db_url() -> str:
    s = get_settings()
    if s.database_url:
        return s.database_url
    pw = f":{s.pgpassword}" if s.pgpassword else ""
    return f"postgresql+asyncpg://{s.pguser}{pw}@{s.pghost}:{s.pgport}/{s.pgdatabase}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def db_conn():
    """Module-scoped connection with test data; tears down after all tests."""
    engine = create_async_engine(_db_url(), echo=False)
    try:
        async with engine.begin() as conn:
            await _setup(conn)
        async with engine.connect() as conn:
            yield conn
    finally:
        async with engine.begin() as conn:
            await _teardown(conn)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Tests (all share the module-scoped event loop via loop_scope="module")
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="module")
async def test_la_excellent_credit(db_conn):
    result = await _find(db_conn, "90210", 25000, 750)
    assert result is not None
    assert result["bank_name"] == "National Credit Union"
    assert result["interest_rate"] == "3.99%"


@pytest.mark.asyncio(loop_scope="module")
async def test_ny_excellent_credit(db_conn):
    result = await _find(db_conn, "10001", 20000, 740)
    assert result is not None
    assert result["bank_name"] == "New York Only CU"
    assert result["interest_rate"] == "3.75%"


@pytest.mark.asyncio(loop_scope="module")
async def test_chicago_good_credit(db_conn):
    result = await _find(db_conn, "60601", 18000, 690)
    assert result is not None
    assert result["bank_name"] == "National Credit Union"
    assert result["interest_rate"] == "5.49%"


@pytest.mark.asyncio(loop_scope="module")
async def test_la_low_loan_amount(db_conn):
    # CA Local CU requires min $10k; National CU accepts $5k+
    result = await _find(db_conn, "90210", 8000, 760)
    assert result is not None
    assert result["bank_name"] == "National Credit Union"
    assert result["interest_rate"] == "3.99%"


@pytest.mark.asyncio(loop_scope="module")
async def test_unrecognized_zipcode_still_finds_nationwide_bank(db_conn):
    """
    Regression test: a zip code not in our zipcode table used to abort the
    whole search immediately, even though nationwide-eligible banks (no
    county restriction) don't actually need to know the county. "77002"
    (Houston, TX) is deliberately not in MOCK_ZIPCODES.
    """
    result = await _find(db_conn, "77002", 25000, 750)
    assert result is not None
    # Only National Credit Union (nationwide) and No Restrictions CU (no
    # region list) are eligible without a known county — National wins on rate.
    assert result["bank_name"] == "National Credit Union"
    assert result["interest_rate"] == "3.99%"


@pytest.mark.asyncio(loop_scope="module")
async def test_unrecognized_zipcode_excludes_county_restricted_banks(db_conn):
    """A bank restricted to a specific county must NOT match when we can't
    determine the user's county — there's nothing to compare against."""
    from app.services.bank_finder import find_best_bank

    result = await find_best_bank(db_conn, zipcode="77002", loan_amount=25000, credit_score=750)
    assert result is not None
    assert result["bank_name"] != "New York Only CU"


@pytest.mark.asyncio(loop_scope="module")
async def test_matching_banks_returns_every_eligible_bank_ranked_by_rate(db_conn):
    from app.services.bank_finder import find_matching_banks

    results = await find_matching_banks(db_conn, zipcode="90210", loan_amount=25000, credit_score=750)

    # This dev DB also has real (non-mock) banks and real seeded zip/county
    # data from other test runs, so don't assert the exact full list or rely
    # on county-restricted "California Local CU" (102, whose eligibility
    # here depends on how the real zipcode table happens to name 90210's
    # county) — just the three mock banks that are unambiguously nationwide
    # regardless of seed data, which is what this test actually needs to
    # verify: multiple ranked offers instead of just one.
    nationwide_mock_ids = {101, 103, 105}  # National, No Restrictions, Empty List
    mock_results = [r for r in results if r["bank_id"] in nationwide_mock_ids]

    names_by_rate = [r["bank_name"] for r in mock_results]
    assert names_by_rate == ["National Credit Union", "Empty List CU", "No Restrictions CU"]
    assert all(
        results[i]["effective_rate"] <= results[i + 1]["effective_rate"]
        for i in range(len(results) - 1)
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_matching_banks_respects_dealer_network_filter(db_conn):
    from app.services.bank_finder import find_matching_banks

    results = await find_matching_banks(
        db_conn, zipcode="90210", loan_amount=25000, credit_score=750, bank_ids=[103, 105]
    )

    assert {r["bank_id"] for r in results} == {103, 105}


@pytest.mark.asyncio(loop_scope="module")
async def test_matching_banks_empty_when_nothing_eligible(db_conn):
    from app.services.bank_finder import find_matching_banks

    # New York Only CU (104) isn't eligible in LA.
    results = await find_matching_banks(
        db_conn, zipcode="90210", loan_amount=25000, credit_score=750, bank_ids=[104]
    )

    assert results == []


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _find(conn, zipcode, loan_amount, credit_score):
    from app.services.bank_finder import find_best_bank
    return await find_best_bank(conn, zipcode=zipcode, loan_amount=loan_amount, credit_score=credit_score)
