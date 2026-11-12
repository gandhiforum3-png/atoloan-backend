"""
Customer-account schema: migrations add the account columns and tables, are
re-runnable, and closing an account (deleting its users row) drops its sessions.
Runs against the local Postgres; skipped when it isn't reachable.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import text

import app.db as db


def _run(coro):
    async def wrapped():
        try:
            return await coro
        finally:
            await db.get_engine().dispose()
            db._engine = None

    return asyncio.run(wrapped())


async def _probe():
    try:
        await db.test_connection()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _run(_probe()), reason="local Postgres not reachable")


async def _columns(table: str) -> set[str]:
    async with db.get_engine().connect() as conn:
        rows = await conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}
        )
        return {r[0] for r in rows}


def test_migrations_add_customer_columns_and_tables():
    from scripts.run_migrations import run

    db._engine = None
    asyncio.run(run())
    db._engine = None
    asyncio.run(run())  # re-runnable
    db._engine = None

    assert {"status", "created_at", "last_login_at"} <= _run(_columns("users"))
    assert "customer_email" in _run(_columns("loan_applications"))
    assert {"email", "code_hash", "expires_at", "attempts", "sends", "window_started_at"} <= _run(
        _columns("customer_login_codes")
    )
    assert {"token_hash", "email", "created_at", "expires_at", "revoked_at"} <= _run(_columns("customer_sessions"))


def test_deleting_user_deletes_their_sessions():
    email = f"schema-{uuid.uuid4().hex[:8]}@example.com"

    async def scenario():
        async with db.get_engine().begin() as conn:
            await conn.execute(
                text("INSERT INTO users (email, first_name, last_name) VALUES (:e, '', '')"), {"e": email}
            )
            await conn.execute(
                text("""INSERT INTO customer_sessions (token_hash, email, expires_at)
                        VALUES (:h, :e, NOW() + INTERVAL '1 hour')"""),
                {"h": uuid.uuid4().hex * 2, "e": email},
            )
            await conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
            return await conn.scalar(text("SELECT COUNT(*) FROM customer_sessions WHERE email = :e"), {"e": email})

    assert _run(scenario()) == 0
