# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

This repo has a nested structure. The active application lives in `atoloan-backend/` (the inner directory):

```
atoloan-backend/          ← outer directory (root)
├── app/                  ← older/reference copy (not actively run)
├── atoloan-backend/      ← ACTIVE application directory
│   ├── .env              ← environment variables (not committed)
│   ├── app/
│   │   ├── main.py       ← FastAPI app, all route definitions
│   │   ├── db.py         ← async SQLAlchemy engine setup
│   │   ├── models/       ← Pydantic models
│   │   ├── services/     ← business logic
│   │   └── integrations/ ← third-party API clients
│   ├── tests/            ← pytest test suite
│   └── requirements.txt
└── tests/                ← older test suite (mirrors inner)
```

**Always work from `atoloan-backend/atoloan-backend/` as the working context** when running the server or tests.

## Commands

```bash
# Activate virtual environment (from repo root)
source .venv/bin/activate

# Install dependencies
pip install -r atoloan-backend/requirements.txt

# Run the dev server (must cd into inner directory first)
cd atoloan-backend
uvicorn app.main:app --reload

# Run tests
cd atoloan-backend
pytest tests/

# Run a single test file
cd atoloan-backend
pytest tests/test_findback.py -v

# Run bank finder tests
cd atoloan-backend
python test_bank_finder.py
```

## Architecture

### Request Flow

1. **PDF Upload** (`POST /ratesheetuploader`): PDF → `pdf_parser_v2.py` (pdfplumber/camelot table merging) → markdown file saved to `upload_pdf/` → `rate_sheet_parser.py` (LangChain/GPT-4 structured extraction) → parsed JSON returned
2. **Rate Sheet Save** (`POST /update`): parsed JSON → `credit_union_mutations.py` → PostgreSQL (`bank_info`, `rate_policy_items`, `loan_program_items`)
3. **Credit Check + Bank Matching** (`POST /findback`): user data → 700Credit API (`seven_hundred.py`) → `bank_finder.py` → best rate returned alongside credit result

### Service Layer (`app/services/`)

| File | Purpose |
|------|---------|
| `pdf_parser_v2.py` | PDF → markdown; detects/merges fragmented tables; primary parser |
| `rate_sheet_parser.py` | LangChain + OpenAI GPT-4 structured extraction from markdown |
| `credit_union_retrieval.py` | All SELECT queries for credit unions, rate policies, loan programs |
| `credit_union_mutations.py` | All INSERT/UPSERT operations (bank_info, rate_policy_items, loan_program_items) |
| `credit_union_deletion.py` | Cascading DELETE for a credit union and all related records |
| `bank_finder.py` | Matches user (zipcode, down payment, credit score) to best bank rate |
| `pdf_validator.py` | Text similarity check between original PDF and generated markdown |

### Database Schema

- `bank_info` — credit union profile, contact, geographic eligibility (`out_region_list` is a PostgreSQL array of counties/states), loan policy flags
- `rate_policy_items` — discounts, rate adjustments, fees (linked to `bank_id`)
- `loan_program_items` — hierarchical: programs → tiers → terms; `item_type` discriminator (`'program'`, `'tier'`, `'term'`); `rate` stored as string (e.g. `"5.25%"`)
- `zipcode` — zipcode-to-city lookup used by bank finder
- `user_table` — user management

### Key Design Patterns

- All DB access uses **async SQLAlchemy** (`AsyncEngine`, `AsyncConnection`). Connections are obtained in route handlers via `engine.begin()` and passed down to service functions — services never create their own connections.
- LangChain parsing is CPU/IO blocking; it runs in a `ThreadPoolExecutor` (4 workers) via `loop.run_in_executor()` to avoid blocking the event loop.
- Pydantic models in `app/models/rate_sheet.py` use `pydantic.v1` compatibility layer (the project pins `pydantic==2.12.5` but models import from `pydantic.v1`).

### Configuration (`.env` in `atoloan-backend/`)

```
PGHOST / PGPORT / PGUSER / PGPASSWORD / PGDATABASE
DATABASE_URL          # overrides individual PG vars if set
OPENAI_API_KEY        # required for LLM rate sheet parsing
SEVENCREDIT_ENV       # "test" or "prod"
SEVENCREDIT_ACCOUNT
SEVENCREDIT_PASSWORD
SEVENCREDIT_CLIENT_ID
SEVENCREDIT_CLIENT_SECRET
```

CORS is configured for `http://localhost:5173` and `http://localhost:5174` (Vite dev servers).
