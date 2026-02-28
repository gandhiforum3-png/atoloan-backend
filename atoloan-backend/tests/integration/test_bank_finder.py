"""
Bank Finder algorithm validation with mock data.

These tests define the expected behaviour of the bank-finder across different
geographic and credit-score scenarios.  The actual live queries are skipped
because bank_finder.py targets the production tables by name; see
test_bank_finder_executable.py for tests that insert/clean real DB rows.
"""
import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.services.bank_finder import find_best_bank

# ---------------------------------------------------------------------------
# Mock dataset
# ---------------------------------------------------------------------------

MOCK_ZIPCODES = [
    {"zipcode": "90210", "city": "Los Angeles County"},
    {"zipcode": "10001", "city": "New York County"},
    {"zipcode": "60601", "city": "Cook County"},
    {"zipcode": "33101", "city": "Miami-Dade County"},
]

MOCK_BANKS = [
    {"bank_id": 1, "name": "National Credit Union",   "accept_out_region_loans": True,  "out_region_list": None},
    {"bank_id": 2, "name": "California Local CU",     "accept_out_region_loans": False, "out_region_list": ["Los Angeles County", "San Diego County"]},
    {"bank_id": 3, "name": "Unrestricted Federal CU", "accept_out_region_loans": False, "out_region_list": None},
    {"bank_id": 4, "name": "New York Only CU",        "accept_out_region_loans": False, "out_region_list": ["New York County"]},
    {"bank_id": 5, "name": "Empty List CU",           "accept_out_region_loans": False, "out_region_list": []},
]

MOCK_LOAN_PROGRAMS = [
    # National Credit Union
    {"bank_id": 1, "program_name": "Prime Auto Loan", "tier_name": "Excellent Credit", "term_in_months": 60, "min_loan_amount": 5000,  "max_loan_amount": 100000, "rate": "3.99%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 1, "program_name": "Prime Auto Loan", "tier_name": "Good Credit",      "term_in_months": 60, "min_loan_amount": 5000,  "max_loan_amount": 100000, "rate": "5.49%", "min_credit_score": 680, "max_credit_score": 719},
    # California Local CU
    {"bank_id": 2, "program_name": "California Auto", "tier_name": "Excellent Credit", "term_in_months": 60, "min_loan_amount": 10000, "max_loan_amount": 80000,  "rate": "4.25%", "min_credit_score": 720, "max_credit_score": 850},
    {"bank_id": 2, "program_name": "California Auto", "tier_name": "Good Credit",      "term_in_months": 60, "min_loan_amount": 10000, "max_loan_amount": 80000,  "rate": "5.75%", "min_credit_score": 680, "max_credit_score": 719},
    # Unrestricted Federal CU
    {"bank_id": 3, "program_name": "Federal Auto",    "tier_name": "Excellent Credit", "term_in_months": 60, "min_loan_amount": 5000,  "max_loan_amount": 75000,  "rate": "4.99%", "min_credit_score": 720, "max_credit_score": 850},
    # New York Only CU
    {"bank_id": 4, "program_name": "NY Auto Loan",    "tier_name": "Excellent Credit", "term_in_months": 60, "min_loan_amount": 8000,  "max_loan_amount": 90000,  "rate": "3.75%", "min_credit_score": 720, "max_credit_score": 850},
    # Empty List CU
    {"bank_id": 5, "program_name": "Standard Auto",   "tier_name": "Excellent Credit", "term_in_months": 60, "min_loan_amount": 5000,  "max_loan_amount": 100000, "rate": "4.49%", "min_credit_score": 720, "max_credit_score": 850},
]

# ---------------------------------------------------------------------------
# Test scenarios (documented expectations)
# ---------------------------------------------------------------------------

TEST_SCENARIOS = [
    {
        "name": "LA – Excellent Credit – High Down Payment",
        "zipcode": "90210", "down_payment": 25000, "credit_score": 750,
        "expected_eligible_bank_ids": [1, 2, 3, 5],
        "expected_best_bank_id": 1, "expected_rate": "3.99%",
    },
    {
        "name": "NY – Excellent Credit – Medium Down Payment",
        "zipcode": "10001", "down_payment": 20000, "credit_score": 740,
        "expected_eligible_bank_ids": [1, 3, 4, 5],
        "expected_best_bank_id": 4, "expected_rate": "3.75%",
    },
    {
        "name": "Chicago – Good Credit – Medium Down Payment",
        "zipcode": "60601", "down_payment": 18000, "credit_score": 690,
        "expected_eligible_bank_ids": [1, 3, 5],
        "expected_best_bank_id": 1, "expected_rate": "5.49%",
    },
    {
        "name": "LA – Excellent Credit – Low Down Payment ($8 k)",
        "zipcode": "90210", "down_payment": 8000, "credit_score": 760,
        "expected_eligible_bank_ids": [1, 3, 5],
        "expected_best_bank_id": 1, "expected_rate": "3.99%",
    },
    {
        "name": "Miami – Excellent Credit – High Down Payment",
        "zipcode": "33101", "down_payment": 30000, "credit_score": 780,
        "expected_eligible_bank_ids": [1, 3, 5],
        "expected_best_bank_id": 1, "expected_rate": "3.99%",
    },
]


def test_mock_data_structure():
    """Verify the mock dataset is internally consistent."""
    bank_ids = {b["bank_id"] for b in MOCK_BANKS}
    for program in MOCK_LOAN_PROGRAMS:
        assert program["bank_id"] in bank_ids, f"Program references unknown bank_id {program['bank_id']}"
    for zipcode in MOCK_ZIPCODES:
        assert zipcode["city"], "Every zipcode must have a city"


def test_scenarios_documented():
    """Confirm all test scenarios have required keys."""
    required = {"name", "zipcode", "down_payment", "credit_score", "expected_best_bank_id", "expected_rate"}
    for scenario in TEST_SCENARIOS:
        missing = required - scenario.keys()
        assert not missing, f"Scenario '{scenario['name']}' missing keys: {missing}"


# NOTE: Live execution tests are in test_bank_finder_executable.py.
# To run against a real DB, use that file which manages its own setup/teardown.
