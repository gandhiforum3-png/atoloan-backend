"""
A verified customer's first pull fills their empty profile (so the next
application is pre-filled); it never overwrites what they've set, and
unverified (dealer/service) pulls never touch an account's profile.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import delete, text

import app.db as db
from app.models.loan_application_table import loan_applications_table as la
from app.services import customer_auth
from app.services.loan_application_mutations import save_findback_result
from tests.integration.conftest import db_available

pytestmark = pytest.mark.skipif(not db_available(), reason="local Postgres not reachable")


def _run(fn):
    async def wrapped():
        try:
            async with db.get_engine().begin() as conn:
                return await fn(conn)
        finally:
            await db.get_engine().dispose()
            db._engine = None

    db._engine = None
    return asyncio.run(wrapped())


@pytest.fixture
def email():
    address = f"pull-{uuid.uuid4().hex[:10]}@example.com"
    yield address

    async def cleanup(conn):
        await conn.execute(delete(la).where(la.c.email == address))
        await conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": address})

    _run(cleanup)


def _pull(email, first_name, address, customer_email):
    return lambda conn: save_findback_result(
        conn, email=email, first_name=first_name, last_name="Doe", address=address, city="San Francisco",
        state="CA", zipcode="94102", phone_number="4155550100", down_payment=None, credit_score=None,
        prequal={"result_code": "0"}, best_bank=None, customer_email=customer_email,
    )


def _profile(email):
    async def read(conn):
        row = await conn.execute(
            text("SELECT first_name, last_name, address, city, state, zipcode, phone_number FROM users WHERE email = :e"),
            {"e": email},
        )
        return tuple(row.one())

    return _run(read)


def test_first_verified_pull_fills_empty_profile(email):
    _run(lambda c: customer_auth.create_session(c, email))
    _run(_pull(email, "Jane", "1 Main St", customer_email=email))
    assert _profile(email) == ("Jane", "Doe", "1 Main St", "San Francisco", "CA", "94102", "4155550100")


def test_later_pulls_never_overwrite_the_profile(email):
    _run(lambda c: customer_auth.create_session(c, email))
    _run(_pull(email, "Jane", "1 Main St", customer_email=email))
    _run(_pull(email, "Janet", "9 New St", customer_email=email))
    assert _profile(email)[:3] == ("Jane", "Doe", "1 Main St")


def test_dealer_pull_never_touches_an_account_profile(email):
    _run(lambda c: customer_auth.create_session(c, email))
    _run(_pull(email, "Mallory", "6 Fake St", customer_email=None))
    assert _profile(email)[:3] == ("", "", None)


def test_dealer_entered_email_is_normalised(email):
    _run(_pull(f"  {email.upper()} ", "Dee", "2 Lot St", customer_email=None))

    async def stored(conn):
        users = await conn.scalar(text("SELECT count(*) FROM users WHERE email = :e"), {"e": email})
        apps = await conn.scalar(text("SELECT count(*) FROM loan_applications WHERE email = :e"), {"e": email})
        return users, apps

    assert _run(stored) == (1, 1)
