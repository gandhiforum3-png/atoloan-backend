# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

This repo has a nested structure. The active application lives in `atoloan-backend/` (the inner directory):

```
atoloan-backend/          ← outer directory (root)
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

1. **PDF Upload** (`POST /ratesheetuploader`): PDF → `rate_sheet_parser.py` (PDF sent directly to Claude, structured output into `CreditUnionRateSheet`) → parsed JSON returned
2. **Rate Sheet Save** (`POST /update`): parsed JSON → `credit_unions.py` → PostgreSQL (`bank_info`, `rate_policy_items`, `loan_program_items`)
3. **Credit Check + Bank Matching** (`POST /findback`): user data → 700Credit API (`seven_hundred.py`) → `bank_finder.py` → best rate returned alongside credit result

### Service Layer (`app/services/`)

| File | Purpose |
|------|---------|
| `rate_sheet_parser.py` | Sends the PDF to Claude; structured output into `CreditUnionRateSheet` |
| `credit_unions.py` | SELECT, UPSERT and cascading DELETE for credit unions, rate policies, loan programs |
| `bank_finder.py` | Matches user (zipcode, down payment, credit score) to best bank rate |

### Database Schema

- `bank_info` — credit union profile, contact, geographic eligibility (`out_region_list` is a PostgreSQL array of counties/states), loan policy flags
- `rate_policy_items` — discounts, rate adjustments, fees (linked to `bank_id`)
- `loan_program_items` — hierarchical: programs → tiers → terms; `item_type` discriminator (`'program'`, `'tier'`, `'term'`); `rate` stored as string (e.g. `"5.25%"`)
- `zipcode` — zipcode-to-city lookup used by bank finder
- `user_table` — user management

### Key Design Patterns

- All DB access uses **async SQLAlchemy** (`AsyncEngine`, `AsyncConnection`). Connections are obtained in route handlers via `engine.begin()` and passed down to service functions — services never create their own connections.
- Rate sheet parsing uses the async Anthropic client (`AsyncAnthropic`, streaming), so it never blocks the event loop.
- Pydantic models in `app/models/rate_sheet.py` are plain Pydantic v2 and double as the structured-output schema for the Claude call.

### Configuration (`.env` in `atoloan-backend/`)

```
PGHOST / PGPORT / PGUSER / PGPASSWORD / PGDATABASE
DATABASE_URL          # overrides individual PG vars if set
ANTHROPIC_API_KEY     # required for LLM rate sheet parsing
SEVENCREDIT_ENV       # "test" or "prod"
SEVENCREDIT_ACCOUNT
SEVENCREDIT_PASSWORD
SEVENCREDIT_CLIENT_ID
SEVENCREDIT_CLIENT_SECRET
SERVICE_TOKEN         # shared with dealer-hub-backend; required (X-Service-Token) on
                      # /credit-unions, /update, /ratesheetuploader, /users. Unset = those routes 401.
ENABLE_DOCS           # true locally to expose /docs; off by default
APP_ENV               # dev/uat/prod from the ConfigMap; empty locally. When set, /auth/request-code
                      # refuses (503) unless TURNSTILE_SECRET_KEY is configured.
DEALER_HUB_BASE_URL   # dealer-hub-backend, for a dealer's bank network on dealer pulls (default :8001)
TURNSTILE_SECRET_KEY  # Cloudflare Turnstile secret (atoloan/turnstile in Secrets Manager)
APP_PGUSER / APP_PGPASSWORD  # migrations only: least-privilege role created for the API to log in as
```

Public routes: `/validate-zipcode`, `/hello`, `/db-check`, and customer sign-in
`/auth/request-code` (Turnstile), `/auth/verify-code`, `/auth/logout`.
Customer-session routes (cookie `atoloan_customer_session`): `/me`, `/findback`,
`/me/applications/{id}/documents`. `/findback` also accepts dealer-hub's X-Service-Token.

CORS is configured for `http://localhost:5173` and `http://localhost:5174` (Vite dev servers),
with credentials. Cross-origin writes from any other Origin get 403 (CSRF guard in `app/main.py`).
