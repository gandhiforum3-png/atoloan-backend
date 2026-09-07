from sqlalchemy import BigInteger, Column, DateTime, MetaData, String, Table, func


metadata = MetaData()

user_table = Table(
    "users",
    metadata,
    Column("email", String(320), primary_key=True),
    # Deterministic hash of the (lowercased) email — see
    # loan_application_mutations.user_id_from_email(). Stable across
    # upserts, and shared with loan_applications.user_id so a user's
    # applications can be joined without depending on raw email matching.
    Column("user_id", BigInteger, unique=True),
    Column("first_name", String(100), nullable=False),
    Column("last_name", String(100), nullable=False),
    Column("address", String(255)),
    Column("city", String(100)),
    Column("state", String(100)),
    Column("zipcode", String(20)),
    Column("phone_number", String(32)),
    Column("drivers_license_key", String(1024)),
    Column("paycheck_key", String(1024)),
    Column(
        "last_modified_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
)
