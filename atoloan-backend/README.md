# ATOLoan Backend

FastAPI backend for the ATOLoan auto loan pre-qualification platform. Handles PDF rate sheet parsing, credit pre-qualification via 700Credit, bank matching, and loan application persistence.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Local Development Setup](#local-development-setup)
- [Environment Variables](#environment-variables)
- [Running the Server](#running-the-server)
- [Running Tests](#running-tests)
- [Database](#database)
- [Key API Endpoints](#key-api-endpoints)
- [Project Structure](#project-structure)
- [Deployment](#deployment)

---

## Architecture Overview

```
User Request
    │
    ▼
FastAPI (uvicorn)
    │
    ├── POST /ratesheetuploader  → PDF → pdfplumber/PyMuPDF → GPT-4 → parsed JSON
    ├── POST /update             → parsed JSON → PostgreSQL (bank_info, rate_policy_items, loan_program_items)
    ├── POST /findback           → 700Credit pre-qual → bank_finder → save loan_application → response
    └── POST /validate-zipcode  → lookup zipcode table → { valid, city }

PostgreSQL (AWS RDS in prod, local in dev)
    ├── bank_info
    ├── rate_policy_items
    ├── loan_program_items
    ├── zipcode               (seeded with 2,657 California zip codes on first deploy)
    ├── users
    └── loan_applications
```

**Tech stack:** Python 3.12 · FastAPI · async SQLAlchemy 2.0 · asyncpg · PostgreSQL 16 · LangChain + OpenAI GPT-4 · pdfplumber · camelot · 700Credit API

---

## Prerequisites

Install these before setting up the project.

### System dependencies

| Dependency | Purpose | Install |
|---|---|---|
| Python 3.12+ | Runtime | `brew install python@3.12` |
| PostgreSQL | Local database | `brew install postgresql@16` |
| Ghostscript | PDF processing (camelot) | `brew install ghostscript` |
| Tesseract OCR | PDF OCR fallback | `brew install tesseract` |
| Poppler | PDF utilities (pdf2image) | `brew install poppler` |

### Accounts / API keys required

| Service | Purpose | Where to get it |
|---|---|---|
| OpenAI | Rate sheet parsing (GPT-4) | platform.openai.com |
| 700Credit | Auto loan pre-qualification | 700credit.com (request a test account from your manager) |

---

## Local Development Setup

```bash
# 1. Clone the repo
git clone <repo-url>
cd atoloan-backend

# 2. Create and activate virtual environment (from repo root)
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r atoloan-backend/requirements.txt

# 4. Create your local .env file (see Environment Variables section below)
cp atoloan-backend/.env.example atoloan-backend/.env
# Then edit .env with your actual values

# 5. Start local PostgreSQL
brew services start postgresql@16

# 6. Create the database
createdb atoloan

# 7. Run database migrations (creates all tables + seeds zip codes)
cd atoloan-backend
python scripts/run_migrations.py

# 8. Start the dev server
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

---

## Environment Variables

Create `atoloan-backend/.env` with the following. **Never commit this file — it is in `.gitignore`.**

```env
# ── Database ─────────────────────────────────────────────────────────────────
PGHOST=localhost
PGPORT=5432
PGUSER=<your-postgres-username>
PGPASSWORD=<your-postgres-password>
PGDATABASE=atoloan

# DATABASE_URL overrides the individual PG vars above if set
# DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/atoloan

# ── OpenAI ───────────────────────────────────────────────────────────────────
OPENAI_API_KEY=sk-...

# ── 700Credit ────────────────────────────────────────────────────────────────
SEVENCREDIT_ENV=test                  # "test" for dev, "prod" for production
SEVENCREDIT_ACCOUNT=<account>
SEVENCREDIT_PASSWORD=<password>
SEVENCREDIT_CLIENT_ID=<client-id>     # optional
SEVENCREDIT_CLIENT_SECRET=<secret>    # optional

# ── CORS ─────────────────────────────────────────────────────────────────────
# Comma-separated list of allowed origins (Vite dev server defaults shown)
CORS_ORIGINS=http://localhost:5173,http://localhost:5174
```

### Variable reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `PGHOST` | Yes | `localhost` | PostgreSQL host |
| `PGPORT` | No | `5432` | PostgreSQL port |
| `PGUSER` | Yes | — | PostgreSQL username |
| `PGPASSWORD` | Yes | — | PostgreSQL password |
| `PGDATABASE` | No | `atoloan` | PostgreSQL database name |
| `DATABASE_URL` | No | — | Full connection string (overrides PG vars) |
| `OPENAI_API_KEY` | Yes* | — | Required for PDF rate sheet parsing |
| `SEVENCREDIT_ENV` | No | `test` | `test` or `prod` |
| `SEVENCREDIT_ACCOUNT` | Yes* | — | Required for `/findback` |
| `SEVENCREDIT_PASSWORD` | Yes* | — | Required for `/findback` |
| `SEVENCREDIT_CLIENT_ID` | No | — | 700Credit OAuth client ID |
| `SEVENCREDIT_CLIENT_SECRET` | No | — | 700Credit OAuth client secret |
| `CORS_ORIGINS` | No | `http://localhost:5173,...` | Comma-separated allowed origins |

*Required for the relevant feature to work; the server starts without them but those endpoints will return errors.

---

## Running the Server

```bash
# Always run from inside atoloan-backend/atoloan-backend/
cd atoloan-backend/atoloan-backend

# Development (auto-reload on file changes)
uvicorn app.main:app --reload

# Production-like (no reload, multiple workers)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

---

## Running Tests

```bash
cd atoloan-backend/atoloan-backend

# All tests
pytest tests/

# Unit tests only (no DB or external APIs needed)
pytest tests/test_findback.py tests/test_loan_application.py -v

# Integration tests (require a live DB and .env)
pytest tests/integration/ -v

# Single file
pytest tests/test_findback.py -v
```

### Test structure

| Path | Type | Requires |
|---|---|---|
| `tests/test_findback.py` | Unit | Nothing |
| `tests/test_loan_application.py` | Unit | Nothing |
| `tests/integration/test_bank_finder*.py` | Integration | Live DB |
| `tests/integration/test_pdf_*.py` | Integration | PDF files + services |
| `tests/integration/test_rate_sheet_parser_*.py` | Integration | `OPENAI_API_KEY` |

---

## Database

### Schema

| Table | Description |
|---|---|
| `bank_info` | Credit union profiles, contact info, geographic eligibility, loan policies |
| `rate_policy_items` | Rate discounts, adjustments, fees per bank |
| `loan_program_items` | Loan programs → tiers → terms (hierarchical, `item_type` discriminator) |
| `zipcode` | Zipcode-to-city/county lookup (2,657 California zip codes pre-seeded) |
| `users` | User accounts (email is unique key) |
| `loan_applications` | Pre-qualification results and matched bank offer per user |

### Migrations

The migration script is idempotent — safe to run on every deploy:

```bash
cd atoloan-backend/atoloan-backend
python scripts/run_migrations.py
```

What it does:
1. Creates all missing tables (`CREATE TABLE IF NOT EXISTS`)
2. Applies additive column changes (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`)
3. Seeds the `zipcode` table from `scripts/california-zip-codes.csv` (skips existing rows)

In Kubernetes, this runs automatically as an **init container** before the API pod starts — no manual migration step needed on deploy.

---

## Key API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/hello` | Health check |
| `POST` | `/ratesheetuploader` | Upload a PDF rate sheet — returns parsed JSON |
| `POST` | `/update` | Save parsed rate sheet to database |
| `POST` | `/findback` | Run 700Credit pre-qual + bank matching |
| `POST` | `/validate-zipcode` | Check if a zip code exists in the database |
| `GET` | `/credit-unions` | List all credit unions |
| `GET` | `/credit-unions/{id}` | Get a single credit union with all rate data |
| `DELETE` | `/credit-unions/{id}` | Delete a credit union and all related records |

Full interactive docs at `http://localhost:8000/docs` when running locally.

---

## Project Structure

```
atoloan-backend/              ← repo root
├── .venv/                    ← virtual environment (not committed)
└── atoloan-backend/          ← active application (always work from here)
    ├── app/
    │   ├── main.py                       ← FastAPI app + router registration
    │   ├── db.py                         ← async SQLAlchemy engine + metadata
    │   ├── core/
    │   │   ├── config.py                 ← Settings (pydantic-settings, lru_cache)
    │   │   └── dependencies.py           ← get_conn async DB dependency
    │   ├── api/routers/
    │   │   ├── health.py                 ← GET /hello
    │   │   ├── rate_sheets.py            ← PDF upload + save
    │   │   ├── credit_unions.py          ← CRUD for credit unions
    │   │   ├── findback.py               ← 700Credit pre-qual + bank finder
    │   │   ├── users.py                  ← user management
    │   │   └── documents.py              ← document upload
    │   ├── services/
    │   │   ├── pdf_parser_hybrid.py      ← picks best of pdfplumber vs PyMuPDF
    │   │   ├── pdf_parser_v2.py          ← pdfplumber + camelot parser
    │   │   ├── rate_sheet_parser.py      ← LangChain + GPT-4 structured extraction
    │   │   ├── bank_finder.py            ← matches user to best bank rate
    │   │   ├── loan_application_mutations.py ← save pre-qual results to DB
    │   │   ├── credit_union_retrieval.py     ← SELECT queries
    │   │   ├── credit_union_mutations.py     ← INSERT/UPSERT queries
    │   │   └── credit_union_deletion.py      ← CASCADE DELETE
    │   ├── models/
    │   │   ├── rate_sheet.py             ← Pydantic v2 models for parsed rate sheets
    │   │   ├── user_table.py             ← SQLAlchemy users table + shared metadata
    │   │   └── loan_application_table.py ← SQLAlchemy loan_applications table
    │   └── integrations/
    │       └── seven_hundred.py          ← 700Credit API client
    ├── scripts/
    │   ├── run_migrations.py             ← DB migration + zipcode seed
    │   ├── california-zip-codes.csv      ← 2,657 CA zip codes
    │   └── benchmark_parsers.py          ← PDF parser accuracy benchmarking
    ├── tests/
    │   ├── test_findback.py              ← unit tests
    │   ├── test_loan_application.py      ← unit tests
    │   └── integration/                  ← integration tests (require live services)
    ├── k8s/
    │   ├── backend-prod-aws.yaml         ← Kubernetes manifests for production
    │   └── backend-dev-aws.yaml          ← Kubernetes manifests for dev
    ├── Dockerfile
    ├── .dockerignore
    ├── requirements.txt
    └── .env                              ← local only, never committed
```

---

## Deployment

### Docker

```bash
cd atoloan-backend/atoloan-backend

# Build for linux/amd64 (required for AWS EC2)
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --no-cache -t gandhiforum3/atoloan-api:latest --load .

# Push to Docker Hub
docker push gandhiforum3/atoloan-api:latest
```

### Kubernetes (Production)

The production cluster is a k3s 2-node setup on AWS (1 server + 1 agent, t3.small).
Secrets are pulled from AWS Secrets Manager via External Secrets Operator.

```bash
# Point kubectl at the prod cluster
export KUBECONFIG=~/.kube/config-aws-prod

# Deploy / update
kubectl apply -f k8s/backend-prod-aws.yaml

# Watch rollout
kubectl rollout status deployment/atoloan-api -n atoloan-backend-prod

# View application logs
kubectl logs -n atoloan-backend-prod -l app=atoloan-api -c api -f

# View migration logs (init container)
kubectl logs -n atoloan-backend-prod -l app=atoloan-api -c db-migrate --tail=50
```

### Required AWS Secrets Manager secrets

These must exist before deploying (created by Terraform in `atoloan-infra`):

| Secret name | Keys |
|---|---|
| `atoloan/postgres-prod` | `PGUSER`, `PGPASSWORD`, `PGHOST`, `PGPORT`, `PGDATABASE` |
| `atoloan/openai` | `OPENAI_API_KEY` |
| `atoloan/sevencredit` | `SEVENCREDIT_ACCOUNT`, `SEVENCREDIT_PASSWORD`, `SEVENCREDIT_CLIENT_ID`, `SEVENCREDIT_CLIENT_SECRET` |
