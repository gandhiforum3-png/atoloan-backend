from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    Table,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

# Share the same metadata instance as user_table so create_tables() covers
# both tables in a single metadata.create_all() call.
from app.models.user_table import metadata

loan_applications_table = Table(
    "loan_applications",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # User identity
    Column("email", String(320)),
    Column("first_name", String(100), nullable=False),
    Column("last_name", String(100), nullable=False),
    Column("address", String(255)),
    Column("city", String(100)),
    Column("state", String(100)),
    Column("zipcode", String(20)),
    Column("phone_number", String(32)),
    # Loan inputs
    Column("down_payment", Numeric(12, 2)),
    Column("credit_score", Integer),
    # 700Credit prequal result
    Column("prequal_result_code", String(50)),
    Column("prequal_result_description", String(500)),
    Column("prequal_score", Integer),
    Column("prequal_tier", String(100)),
    Column("prequal_score_range", String(100)),
    Column("prequal_transid", String(100)),
    Column("prequal_raw", JSONB),
    # Best bank offer
    Column("bank_id", Integer),
    Column("bank_name", String(255)),
    Column("interest_rate", String(20)),
    Column("program_name", String(255)),
    Column("tier_name", String(100)),
    Column("term_in_months", Integer),
    Column("min_loan_amount", Integer),
    Column("max_loan_amount", Integer),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)
