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
   - OpenAI API key for LLM parsing
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
- `GET /ratesheetuploader/markdown/{filename}` - Download parsed markdown
- `POST /parse-rate-sheet-markdown` - Parse markdown to structured data

### General
- `GET /hello` - Health check
- `GET /db-check` - Database connection check
- `POST /echo` - Echo request payload

## 🏗️ Architecture

### Database Services (Refactored)

The codebase uses a clean separation of concerns with dedicated service modules:

- **`credit_union_retrieval.py`** - All GET/SELECT operations
  - `get_all_credit_unions()` - List credit unions
  - `get_bank_info()` - Get detailed bank information
  - `get_rate_policy()` - Get rate policies
  - `get_loan_programs()` - Get loan programs with hierarchical structure

- **`credit_union_mutations.py`** - All INSERT/UPSERT operations
  - `upsert_bank_info()` - Upsert bank information
  - `upsert_rate_policy_items()` - Upsert rate policies
  - `upsert_loan_program_items()` - Upsert loan programs

- **`credit_union_deletion.py`** - All DELETE operations
  - `delete_credit_union_and_related()` - Delete credit union and related data

## 📋 PDF Parser Features

### Intelligent Table Merging
Automatically detects and merges fragmented tables in PDF rate sheets.

**Example - SF FIRE CU.pdf**:
```
6 separate table regions → 2 comprehensive merged tables
All rate data preserved: 49-60 MOS, 61-72 MOS, 73-84 MOS
Result: 95% similarity with original PDF
```

### Parser Components
- `pdf_parser_v2.py` - Main unified parser with table merging
- `pdf_validator.py` - Validation system for accuracy checking
- `rate_sheet_parser.py` - LLM-based structured data extraction

## ✅ Test Results

### Parse Success Rate
- **10/10 PDFs** parsed successfully ✅
- **0 errors** during batch processing ✅
- **95%+ similarity** across all PDFs ✅

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
- **LangChain + OpenAI GPT-4** - Structured data extraction from PDFs
- **pdfplumber + pytesseract** - PDF text extraction
- **700Credit API** - Credit check integration

## 📚 Documentation

For detailed documentation on specific features, see:
- Test files: `test_*.py` for usage examples
- Service modules in `app/services/` for implementation details

---

**Status**: ✅ Production Ready
**Last Updated**: February 10, 2026
