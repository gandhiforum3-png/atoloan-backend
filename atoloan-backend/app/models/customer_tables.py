"""
Customer sign-in: one pending email code per address, and server-side sessions
(revocable, so sign-out-everywhere and admin disable take effect at once).
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, func

from app.models.user_table import metadata

customer_login_codes_table = Table(
    "customer_login_codes",
    metadata,
    Column("email", String(320), primary_key=True),
    # HMAC-SHA256 of email + code — never the code itself
    Column("code_hash", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    # Send cap: codes sent since window_started_at (rolling hour)
    Column("sends", Integer, nullable=False, server_default="0"),
    Column("window_started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Wrong guesses in the last 24h across ALL codes — a new code doesn't reset it
    Column("failures", Integer, nullable=False, server_default="0"),
    Column("failures_window_started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

customer_sessions_table = Table(
    "customer_sessions",
    metadata,
    # SHA-256 of the cookie token — a DB leak yields no live sessions
    Column("token_hash", String(64), primary_key=True),
    Column("email", String(320), ForeignKey("users.email", ondelete="CASCADE"), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
)
