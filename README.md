# ATOLoan Backend

FastAPI backend for auto loan processing with PDF rate sheet parsing, credit checks, and comprehensive credit union management.

## 🚀 Quick Start

### Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r atoloan-backend/requirements.txt
```

### Configuration

1. Copy `.env.example` to `.env` in the `atoloan-backend` directory
2. Configure your database and API keys:
   - PostgreSQL connection details
   - Anthropic API key for LLM parsing
   - 700Credit API credentials

### Run

```bash
cd atoloan-backend
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`

## 📡 API Endpoints

### Credit Union Management
- `GET /credit-unions` - List all credit unions
- `GET /credit-unions/{id}/ratesheet` - Get complete rate sheet for a credit union
- `DELETE /credit-unions/{id}` - Delete credit union and all related data
- `POST /update` - Upsert credit union rate sheet data

### Credit Checks
- `POST /findback` - Submit credit check request to 700Credit
- `POST /validate-zipcode` - Validate zipcode

### Rate Sheet Processing
- `POST /ratesheetuploader` - Upload PDF rate sheet for parsing

### General
- `GET /hello` - Health check
- `GET /db-check` - Database connection check
- `POST /echo` - Echo request payload

## 🏗️ Architecture

### Database Services (Refactored)

The codebase uses a clean separation of concerns with dedicated service modules:

- **`credit_unions.py`** - All credit union DB operations
  - `get_all_credit_unions()` - List credit unions
  - `get_bank_info()` - Get detailed bank information
  - `get_rate_policy()` - Get rate policies
  - `get_loan_programs()` - Get loan programs with hierarchical structure
  - `upsert_bank_info()` - Upsert bank information
  - `upsert_rate_policy_items()` - Upsert rate policies
  - `upsert_loan_program_items()` - Upsert loan programs
  - `delete_credit_union_and_related()` - Delete credit union and related data

## 📋 Rate Sheet Parsing

`rate_sheet_parser.py` sends the uploaded PDF straight to Claude (Opus 5.5) and gets back a validated
`CreditUnionRateSheet` via structured outputs — there is no local PDF→markdown step.

## 🗄️ Database Schema

### Tables
- `bank_info` - Credit union information and policies
- `rate_policy_items` - Discounts, adjustments, and fees
- `loan_program_items` - Loan programs with hierarchical structure (programs → tiers → terms)
- `user_table` - User management
- `zipcode` - Zipcode validation data

## 🛠️ Technology Stack

- **FastAPI** - Modern async web framework
- **PostgreSQL** - Database with asyncpg driver
- **SQLAlchemy** - Async ORM
- **Anthropic Claude** - Structured data extraction directly from PDFs
- **700Credit API** - Credit check integration

## 📚 Documentation

For detailed documentation on specific features, see:
- Test files: `test_*.py` for usage examples
- Service modules in `app/services/` for implementation details

---

**Status**: ✅ Production Ready
**Last Updated**: February 10, 2026
