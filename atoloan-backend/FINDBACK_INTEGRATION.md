# /findback Endpoint - Bank Finder Integration

## Overview
The `/findback` endpoint now integrates the bank finder algorithm to automatically recommend the best bank offer after completing the 700Credit check.

## How It Works

1. **Credit Check**: Submits user information to 700Credit API
2. **Bank Finder**: Automatically finds the best bank based on:
   - User's zipcode (from credit check request)
   - Credit score (from 700Credit response)
   - Down payment amount (from request payload)

## Request Format

### Required Fields
```json
{
  "contactInfo": {
    "firstName": "John",
    "lastName": "Doe",
    "address": "123 Main St",
    "city": "Los Angeles",
    "state": "CA",
    "zip": "90210"
  },
  "ssn": "123-45-6789",
  "down_payment": 25000,  // ⭐ NEW - Required for bank finder
  "bureau": "TU",
  "app_modified": false
}
```

### Alternative Format (Flattened)
```json
{
  "first_name": "John",
  "last_name": "Doe",
  "address": "123 Main St",
  "city": "Los Angeles",
  "state": "CA",
  "zip_code": "90210",
  "ssn": "123-45-6789",
  "down_payment": 25000,  // ⭐ NEW - Required for bank finder
  "bureau": "TU",
  "app_modified": false
}
```

## Response Format

### Successful Response with Bank Recommendation
```json
{
  "prequal": {
    "credit_score": 750,
    "status": "approved",
    // ... other 700Credit response fields ...
  },
  "best_bank": {  // ⭐ NEW - Bank finder results
    "bank_id": 1,
    "bank_name": "National Credit Union",
    "interest_rate": "3.99%",
    "program_name": "Prime Auto Loan",
    "tier_name": "Excellent Credit",
    "term_in_months": 60,
    "min_loan_amount": 5000,
    "max_loan_amount": 100000,
    "min_credit_score": 720,
    "max_credit_score": 850
  }
}
```

### Response When Bank Finder Cannot Run
```json
{
  "prequal": {
    // ... 700Credit response ...
  },
  "bank_finder_error": "Missing required parameters: down_payment"
}
```

### Response When No Eligible Banks Found
```json
{
  "prequal": {
    // ... 700Credit response ...
  },
  "best_bank": null
}
```

## Bank Finder Logic

### Eligibility Criteria
A bank is eligible if:
1. `accept_out_region_loans = true` (nationwide eligibility), OR
2. `out_region_list IS NULL OR = []` (no restrictions = nationwide), OR
3. User's county is in the bank's `out_region_list`

### Matching Criteria
For eligible banks, the algorithm finds programs that match:
- Credit score falls within `[min_credit_score, max_credit_score]`
- Down payment falls within `[min_loan_amount, max_loan_amount]`

### Best Rate Selection
- Returns the bank with the **lowest interest rate** among all eligible matches

## Parameter Extraction

### Credit Score
The bank finder attempts to extract the credit score from the 700Credit response in this order:
1. `prequal_data.credit_score`
2. `prequal_data.score`
3. `prequal_data.fico_score`
4. `prequal_data.bureau_response.credit_score`
5. `prequal_data.bureau_response.score`
6. `prequal_data.bureau_response.fico_score`

### Down Payment
Must be provided in the request payload as `down_payment` (numeric value in dollars).

### Zipcode
Extracted from the credit check request (`zip` or `zip_code`).

## Error Handling

### Bank Finder Errors Don't Block Credit Check
- If bank finder fails, the 700Credit response is still returned
- Error is included in `bank_finder_error` field
- This ensures credit checks succeed even if bank finder has issues

### Missing Parameters
If any required parameter is missing:
- Bank finder is skipped
- `bank_finder_error` explains which parameters are missing
- 700Credit response is still returned normally

### No Eligible Banks
If no banks match the user's criteria:
- `best_bank` will be `null`
- No error is set (this is a valid result)

## Example cURL Request

```bash
curl -X POST http://127.0.0.1:8000/findback \
  -H "Content-Type: application/json" \
  -d '{
    "contactInfo": {
      "firstName": "John",
      "lastName": "Doe",
      "address": "123 Main St",
      "city": "Los Angeles",
      "state": "CA",
      "zip": "90210"
    },
    "ssn": "123-45-6789",
    "down_payment": 25000,
    "bureau": "TU"
  }'
```

## Logging

The integration adds detailed logging:

### Bank Finder Execution
```
[BANK FINDER] Running with zipcode=90210, down_payment=25000, credit_score=750
```

### Success
```
[BANK FINDER] Found best offer: National Credit Union at 3.99%
```

### No Results
```
[BANK FINDER] No eligible banks found for user criteria
```

### Missing Parameters
```
[BANK FINDER] Skipped - missing parameters: down_payment
```

### Errors
```
[BANK FINDER] Error finding best bank: <error message>
```

## Benefits

1. **Seamless Integration**: One API call provides both credit check and bank recommendation
2. **Fault Tolerant**: Bank finder errors don't block credit check
3. **Automatic Matching**: No manual bank selection needed
4. **Best Rate Guaranteed**: Always returns the lowest available rate

## Next Steps

### Frontend Integration
Update your frontend to:
1. Include `down_payment` in the `/findback` request
2. Display the `best_bank` results to the user
3. Handle cases where `best_bank` is `null` or `bank_finder_error` exists

### Testing
Use the validation test data:
```bash
python test_bank_finder_executable.py
```

This ensures the bank finder algorithm works correctly with your database.

---

**Last Updated**: February 10, 2026
