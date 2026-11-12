"""_owns_application against the local Postgres: only pulls run while signed
in belong to the account — a guest application with the same email does not."""
import asyncio
import uuid

import pytest
from sqlalchemy import delete, insert

import app.db as db
from app.api.routers.documents import _owns_application
from app.models.loan_application_table import loan_applications_table as la


def _run(coro_fn):
    async def wrapped():
        try:
            return await coro_fn()
        finally:
            await db.get_engine().dispose()
            db._engine = None

    db._engine = None
    return asyncio.run(wrapped())


def _available():
    try:
        _run(db.test_connection)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="local Postgres not reachable")


def test_only_signed_in_pulls_are_owned():
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"

    async def scenario():
        async with db.get_engine().begin() as conn:
            ids = (
                await conn.execute(
                    insert(la).returning(la.c.id),
                    [
                        {"first_name": "A", "last_name": "B", "email": email, "customer_email": email},
                        {"first_name": "A", "last_name": "B", "email": email, "customer_email": None},  # guest
                        {"first_name": "C", "last_name": "D", "email": "x@example.com", "customer_email": "x@example.com"},
                    ],
                )
            ).scalars().all()
        try:
            return [await _owns_application(i, email) for i in ids]
        finally:
            async with db.get_engine().begin() as conn:
                await conn.execute(delete(la).where(la.c.id.in_(ids)))

    assert _run(scenario) == [True, False, False]
