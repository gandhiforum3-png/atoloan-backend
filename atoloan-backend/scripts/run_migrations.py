"""
Database migration script — run this before starting the API server.

Executed by the Kubernetes init container on every deployment.
Safe to run repeatedly: all statements use IF NOT EXISTS / IF EXISTS guards.

What it does:
  1. Creates all tables that don't exist yet (via SQLAlchemy metadata.create_all).
  2. Runs additive ALTER TABLE statements for columns added after initial schema
     creation (these are idempotent — IF NOT EXISTS).
  3. Exits 0 on success, non-zero on failure (causing the init container to
     fail and preventing the API pod from starting).
"""

import asyncio
import logging
import sys
from pathlib import Path

# Ensure the project root (parent of scripts/) is on sys.path so `app` is importable
# whether running locally or inside the Docker container (CWD=/app).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load .env when running locally (no-op in production where env vars are injected)
_env_file = _ROOT / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file, override=False)

from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tables not managed by SQLAlchemy metadata — created via raw DDL.
# Order matters: respect foreign key dependencies.
#   1. bank_info (no deps)
#   2. zipcode   (no deps)
#   3. rate_policy_items  (FK → bank_info)
#   4. loan_program_items (FK → bank_info, rate_policy_items)
# ---------------------------------------------------------------------------
_CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS bank_info (
        bank_id                             SERIAL PRIMARY KEY,
        name                                TEXT UNIQUE,
        effective_date                      DATE,
        replaces_rate_sheet_date            DATE,
        address                             TEXT,
        contact_phone                       TEXT,
        contact_fax                         TEXT,
        contact_email                       TEXT,
        contact_website                     TEXT,
        contact_person                      TEXT,
        membership_eligibility              TEXT,
        branch_locations                    TEXT[],
        notes                               TEXT,
        maximum_debt_to_income_ratio        TEXT,
        is_cosigner_allowed                 BOOLEAN,
        is_cosigner_same_address_required   BOOLEAN,
        cosigner_requirement_guidelines     TEXT[],
        accept_out_region_loans             BOOLEAN,
        out_region_list                     TEXT[],
        is_credit_union_member_required     BOOLEAN,
        ftd_is_participant                  BOOLEAN,
        ftd_guidelines                      TEXT[],
        ftd_description                     TEXT,
        ftd_max_amount                      TEXT,
        ftd_max_term                        TEXT,
        ftd_ltv                             TEXT,
        ftd_fico_pricing                    TEXT,
        ftd_requirements                    TEXT,
        subprime_description                TEXT,
        subprime_fico_limit                 TEXT,
        subprime_max_amount                 TEXT,
        subprime_max_term                   TEXT,
        subprime_ltv                        TEXT,
        subprime_income_proof_required      TEXT,
        subprime_auto_history_requirement   TEXT,
        dealer_participation_percentage     TEXT,
        dealer_participation_minimum        TEXT,
        dealer_participation_maximum        TEXT,
        dealer_participation_conditions     TEXT,
        chargeback_policy                   TEXT,
        funding_method                      TEXT,
        funding_contact_email               TEXT,
        funding_contact_phone               TEXT,
        funding_hours                       TEXT,
        funding_address                     TEXT,
        lien_holder_name                    TEXT,
        lien_holder_mailing_address         TEXT,
        lien_holder_physical_address        TEXT,
        lien_holder_insurance_address       TEXT,
        lien_holder_electronic_lien_code    TEXT,
        disclaimers                         TEXT[],
        rate_change_policy                  TEXT,
        eligibility_notes                   TEXT,
        other_comments                      TEXT,
        created_at                          TIMESTAMP DEFAULT NOW(),
        updated_at                          TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zipcode (
        zipcode  TEXT PRIMARY KEY,
        city     TEXT,
        county   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rate_policy_items (
        id          SERIAL PRIMARY KEY,
        bank_id     INTEGER NOT NULL REFERENCES bank_info(bank_id) ON DELETE CASCADE,
        item_type   TEXT NOT NULL,
        description TEXT NOT NULL,
        value       TEXT,
        value_type  TEXT,
        conditions  TEXT,
        created_at  TIMESTAMP DEFAULT NOW(),
        updated_at  TIMESTAMP DEFAULT NOW(),
        UNIQUE (bank_id, item_type, description)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS loan_program_items (
        loan_program_id  SERIAL PRIMARY KEY,
        bank_id          INTEGER NOT NULL REFERENCES bank_info(bank_id) ON DELETE CASCADE,
        rate_policy_id   INTEGER REFERENCES rate_policy_items(id) ON DELETE SET NULL,
        item_type        TEXT NOT NULL,
        parent_id        INTEGER,
        program_name     TEXT,
        vehicle_type     TEXT,
        model_year_range TEXT,
        min_model_year   INTEGER,
        max_model_year   INTEGER,
        mileage_limit    TEXT,
        base_ltv         TEXT,
        max_ltv          TEXT,
        ltv_notes        TEXT,
        tier_name        TEXT,
        credit_score_range TEXT,
        min_credit_score INTEGER,
        max_credit_score INTEGER,
        term_in_months   INTEGER,
        min_loan_amount  INTEGER,
        max_loan_amount  INTEGER,
        rate             TEXT,
        term_conditions  TEXT,
        created_at       TIMESTAMP DEFAULT NOW(),
        updated_at       TIMESTAMP DEFAULT NOW(),
        UNIQUE (bank_id, item_type, program_name, tier_name, term_in_months)
    )
    """,
]

# Additive ALTER TABLE statements — add a line here whenever a column is
# added to an already-existing table.
_ALTER_STATEMENTS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(100)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR(100)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS zipcode VARCHAR(20)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS drivers_license_key VARCHAR(1024)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS paycheck_key VARCHAR(1024)",
    # Rate sheet schema optimization (docs/rate_sheet_schema_optimization.md), Phase 1 (#1-#4):
    # numeric fields derived alongside the existing free-text ones so matching/ranking
    # doesn't have to re-parse strings at query time. NULL on rows ingested before this
    # migration until that bank's rate sheet is re-uploaded.
    "ALTER TABLE bank_info ADD COLUMN IF NOT EXISTS maximum_debt_to_income_ratio_value NUMERIC",
    "ALTER TABLE loan_program_items ADD COLUMN IF NOT EXISTS base_ltv_value NUMERIC",
    "ALTER TABLE loan_program_items ADD COLUMN IF NOT EXISTS max_ltv_value NUMERIC",
    "ALTER TABLE loan_program_items ADD COLUMN IF NOT EXISTS mileage_limit_value INTEGER",
    "ALTER TABLE loan_program_items ADD COLUMN IF NOT EXISTS rate_value NUMERIC",
    # Rate sheet schema optimization, Phase 2 (#6, #9, #10): constrained categorical fields
    # (values are enforced at the Pydantic/LLM-extraction layer via Literal types, not a DB
    # CHECK constraint, matching how item_type/value_type are already handled).
    "ALTER TABLE bank_info ADD COLUMN IF NOT EXISTS credit_bureau TEXT",
    "ALTER TABLE bank_info ADD COLUMN IF NOT EXISTS credit_score_model TEXT",
    "ALTER TABLE rate_policy_items ADD COLUMN IF NOT EXISTS fee_category TEXT",
    "ALTER TABLE loan_program_items ADD COLUMN IF NOT EXISTS tier_rank INTEGER",
    # Rate sheet schema optimization, Phase 6 (#28, #30): condition classification for
    # discounts/adjustments, and multi-path membership eligibility, so bank_finder can apply
    # discounts and pre-filter by membership without re-parsing free text at query time.
    "ALTER TABLE rate_policy_items ADD COLUMN IF NOT EXISTS condition_type TEXT",
    "ALTER TABLE rate_policy_items ADD COLUMN IF NOT EXISTS threshold_value NUMERIC",
    "ALTER TABLE bank_info ADD COLUMN IF NOT EXISTS membership_paths TEXT[]",
    # Dealer-scoped soft pull: link an application to the dealer who ran it,
    # and store every matched bank's own offer (not just the single best).
    "ALTER TABLE loan_applications ADD COLUMN IF NOT EXISTS dealer_id VARCHAR(20)",
    "ALTER TABLE loan_applications ADD COLUMN IF NOT EXISTS matched_banks JSONB",
    # Deterministic per-email user_id (see loan_application_mutations.user_id_from_email) —
    # a stable join key across users/loan_applications independent of raw email matching.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS user_id BIGINT",
    # Postgres has no ADD CONSTRAINT IF NOT EXISTS for UNIQUE — a unique
    # index is the idempotent equivalent.
    "CREATE UNIQUE INDEX IF NOT EXISTS users_user_id_key ON users (user_id)",
    "ALTER TABLE loan_applications ADD COLUMN IF NOT EXISTS user_id BIGINT",
]


async def run() -> None:
    # Import here so env vars are already loaded before SQLAlchemy reads them
    from app.db import get_engine, metadata  # noqa: PLC0415

    engine = get_engine()
    logger.info("Running migrations...")

    async with engine.begin() as conn:
        # Step 1: raw DDL tables (bank_info, zipcode, rate_policy_items, loan_program_items)
        logger.info("Creating core tables...")
        for stmt in _CREATE_STATEMENTS:
            await conn.execute(text(stmt))
        logger.info("Core tables OK")

        # Step 2: SQLAlchemy-managed tables (users, loan_applications)
        logger.info("Creating metadata-managed tables...")
        await conn.run_sync(metadata.create_all)
        logger.info("Metadata tables OK")

        # Step 3: additive column migrations on existing tables
        for stmt in _ALTER_STATEMENTS:
            logger.info("Executing: %s", stmt.strip())
            await conn.execute(text(stmt))

        # Step 4: seed zipcode table from CSV (ON CONFLICT DO NOTHING — idempotent)
        await _seed_zipcodes(conn)

        # Step 5: backfill user_id for rows written before that column existed
        await _backfill_user_ids(conn)

    logger.info("All migrations complete — 6 tables ready.")


async def _backfill_user_ids(conn) -> None:
    from app.services.loan_application_mutations import user_id_from_email  # noqa: PLC0415

    result = await conn.execute(text("SELECT email FROM users WHERE user_id IS NULL"))
    emails = [row[0] for row in result.fetchall()]
    for email in emails:
        uid = user_id_from_email(email)
        await conn.execute(
            text("UPDATE users SET user_id = :uid WHERE email = :email"),
            {"uid": uid, "email": email},
        )
        await conn.execute(
            text("UPDATE loan_applications SET user_id = :uid WHERE email = :email AND user_id IS NULL"),
            {"uid": uid, "email": email},
        )
    if emails:
        logger.info("Backfilled user_id for %d user(s)", len(emails))


async def _seed_zipcodes(conn) -> None:
    import csv

    csv_path = Path(__file__).parent / "california-zip-codes.csv"
    if not csv_path.exists():
        logger.warning("Zipcode CSV not found at %s — skipping seed", csv_path)
        return

    # Read CSV
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            zipcode = row.get("Zip Code", "").strip()
            city    = row.get("City", "").strip()
            county  = row.get("County", "").strip()
            if zipcode:
                rows.append({"zipcode": zipcode, "city": city, "county": county})

    if not rows:
        logger.warning("Zipcode CSV is empty — skipping seed")
        return

    # Bulk insert in batches of 500, skip any already-existing rows
    batch_size = 500
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        values_clause = ", ".join(
            f"('{r['zipcode']}', '{r['city'].replace(chr(39), chr(39)*2)}', '{r['county'].replace(chr(39), chr(39)*2)}')"
            for r in batch
        )
        result = await conn.execute(text(f"""
            INSERT INTO zipcode (zipcode, city, county)
            VALUES {values_clause}
            ON CONFLICT (zipcode) DO NOTHING
        """))
        inserted += result.rowcount

    logger.info("Zipcode seed: %d/%d rows inserted (rest already existed)", inserted, len(rows))


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception:
        logger.exception("Migration failed")
        sys.exit(1)
