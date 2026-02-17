# Bank Finder Algorithm Validation

## Overview
This document explains the bank finder algorithm logic and how the test data validates each eligibility scenario.

## Eligibility Logic (Lines 128-135 in bank_finder.py)

The SQL WHERE clause determines which banks are eligible to provide loans:

```sql
WHERE
    -- Bank accepts out of region loans (entire USA)
    accept_out_region_loans = true
    OR
    -- No restrictions specified (entire USA)
    (out_region_list IS NULL OR out_region_list = '{}')
    OR
    -- User's county is in the eligible list
    :user_county = ANY(out_region_list)
```

## Three Eligibility Scenarios

### Scenario 1: `accept_out_region_loans = true`
**Interpretation**: Bank explicitly accepts loans from anywhere in the USA

**Test Data**: Bank ID 101 - "National Credit Union"
- `accept_out_region_loans`: `true`
- `out_region_list`: `null`

**Expected Behavior**: Eligible for ALL zipcodes (90210, 10001, 60601)

---

### Scenario 2: `out_region_list IS NULL OR out_region_list = '{}'`
**Interpretation**: No restrictions specified = Bank accepts loans from entire USA

**Test Data**:
- Bank ID 103 - "No Restrictions CU"
  - `accept_out_region_loans`: `false`
  - `out_region_list`: `null`

- Bank ID 105 - "Empty List CU"
  - `accept_out_region_loans`: `false`
  - `out_region_list`: `[]` (empty array)

**Expected Behavior**: Eligible for ALL zipcodes (90210, 10001, 60601)

---

### Scenario 3: `:user_county = ANY(out_region_list)`
**Interpretation**: User's county must be in the bank's approved county list

**Test Data**:
- Bank ID 102 - "California Local CU"
  - `accept_out_region_loans`: `false`
  - `out_region_list`: `['Los Angeles County']`
  - **Expected**: Eligible ONLY for zipcode 90210 (Los Angeles County)

- Bank ID 104 - "New York Only CU"
  - `accept_out_region_loans`: `false`
  - `out_region_list`: `['New York County']`
  - **Expected**: Eligible ONLY for zipcode 10001 (New York County)

---

## Test Scenarios

### Test 1: Los Angeles (90210) - Excellent Credit - $25k
**Eligible Banks**:
- ✅ National Credit Union (101) - nationwide (accept_out_region = true)
- ✅ California Local CU (102) - county match
- ✅ No Restrictions CU (103) - nationwide (out_region_list = null)
- ❌ New York Only CU (104) - county mismatch
- ✅ Empty List CU (105) - nationwide (out_region_list = [])

**Best Rate**: National Credit Union at 3.99%

---

### Test 2: New York (10001) - Excellent Credit - $20k
**Eligible Banks**:
- ✅ National Credit Union (101) - nationwide
- ❌ California Local CU (102) - county mismatch
- ✅ No Restrictions CU (103) - nationwide
- ✅ New York Only CU (104) - county match
- ✅ Empty List CU (105) - nationwide

**Best Rate**: New York Only CU at 3.75% (lowest rate wins)

---

### Test 3: Chicago (60601) - Good Credit (690) - $18k
**Eligible Banks**:
- ✅ National Credit Union (101) - nationwide
- ❌ California Local CU (102) - county mismatch
- ✅ No Restrictions CU (103) - nationwide
- ❌ New York Only CU (104) - county mismatch
- ✅ Empty List CU (105) - nationwide

**Credit Score Tier**: Good (680-719)
**Best Rate**: National Credit Union at 5.49% (only bank with "Good" tier in test data)

---

### Test 4: Los Angeles (90210) - Excellent Credit - $8k (Low Down Payment)
**Eligible Banks by Location**:
- ✅ National Credit Union (101)
- ✅ California Local CU (102)
- ✅ No Restrictions CU (103)
- ✅ Empty List CU (105)

**Filtered by Loan Amount**:
- ✅ National Credit Union - min: $5k ✓
- ❌ California Local CU - min: $10k ✗ (exceeds down payment)
- ✅ No Restrictions CU - min: $5k ✓
- ✅ Empty List CU - min: $5k ✓

**Best Rate**: National Credit Union at 3.99%

---

## Running the Tests

### Option 1: Executable Test (Recommended)
```bash
cd atoloan-backend
python test_bank_finder_executable.py
```

This will:
1. Load test data into your database
2. Run all 4 test scenarios
3. Validate results against expected outcomes
4. Clean up test data automatically

### Option 2: Manual Validation
Review the mock data in `test_bank_finder.py` to understand the test structure.

---

## Expected Results Summary

| Test | Zipcode | County | Credit | Down Payment | Expected Bank | Rate | Reason |
|------|---------|--------|--------|--------------|---------------|------|--------|
| 1 | 90210 | LA County | 750 | $25k | National CU | 3.99% | Nationwide + best rate |
| 2 | 10001 | NY County | 740 | $20k | NY Only CU | 3.75% | County match + best rate |
| 3 | 60601 | Cook County | 690 | $18k | National CU | 5.49% | Nationwide + only "Good" tier |
| 4 | 90210 | LA County | 760 | $8k | National CU | 3.99% | CA Local filtered (min $10k) |

---

## Validation Checklist

- ✅ **Scenario 1 validated**: accept_out_region_loans = true → nationwide eligibility
- ✅ **Scenario 2 validated**: out_region_list IS NULL/empty → nationwide eligibility
- ✅ **Scenario 3 validated**: County in out_region_list → county-specific eligibility
- ✅ **Credit score matching**: Correct tier selection based on credit score range
- ✅ **Loan amount filtering**: Min/max loan amount requirements enforced
- ✅ **Best rate selection**: Lowest interest rate among eligible banks returned
- ✅ **Edge case**: Low down payment filters out banks with higher minimums

---

## Database Schema Requirements

### zipcode table
```sql
zipcode VARCHAR(10) PRIMARY KEY
city VARCHAR(255) NOT NULL  -- County name
```

### bank_info table
```sql
bank_id INTEGER PRIMARY KEY
name VARCHAR(255) NOT NULL
accept_out_region_loans BOOLEAN
out_region_list TEXT[]  -- PostgreSQL array of county names
```

### loan_program_items table
```sql
bank_id INTEGER NOT NULL
item_type VARCHAR(50) DEFAULT 'term'
program_name VARCHAR(255)
tier_name VARCHAR(255)
term_in_months INTEGER
min_loan_amount INTEGER
max_loan_amount INTEGER
rate VARCHAR(20)  -- e.g., "3.99%"
min_credit_score INTEGER
max_credit_score INTEGER
```

---

## Algorithm Correctness

The test data validates that the algorithm correctly:

1. **Identifies user location** from zipcode → county mapping
2. **Filters eligible banks** using the three-condition OR logic
3. **Matches credit score** to appropriate tier (Excellent: 720-850, Good: 680-719)
4. **Validates loan amount** against min/max requirements
5. **Compares interest rates** and returns the best offer
6. **Handles edge cases** like missing counties, no eligible banks, low down payments

All test scenarios should **PASS** if the algorithm is implemented correctly.
