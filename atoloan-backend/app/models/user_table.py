from sqlalchemy import BigInteger, Column, DateTime, Identity, MetaData, String, Table, func


metadata = MetaData()

user_table = Table(
    "users",
    metadata,
    Column("email", String(320), primary_key=True),
    # Opaque handle for admin URLs — emails in paths end up in access logs
    Column("id", BigInteger, Identity(), unique=True, nullable=False),
    Column("first_name", String(100), nullable=False),
    Column("last_name", String(100), nullable=False),
    Column("address", String(255)),
    Column("city", String(100)),
    Column("state", String(100)),
    Column("zipcode", String(20)),
    Column("phone_number", String(32)),
    Column("drivers_license_key", String(1024)),
    Column("paycheck_key", String(1024)),
    # Customer account: 'active' | 'disabled' (admin-controlled)
    Column("status", String(20), nullable=False, server_default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_login_at", DateTime(timezone=True)),
    Column(
        "last_modified_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
)
