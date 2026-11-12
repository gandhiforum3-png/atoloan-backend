"""
Sign-in codes and sessions against the local Postgres (skipped when unreachable).
"""
import asyncio
import uuid

import pytest
from sqlalchemy import text

import app.db as db
from app.services import customer_auth as auth


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


def _available() -> bool:
    try:
        return _run(lambda conn: conn.scalar(text("SELECT 1"))) == 1
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="local Postgres not reachable")


@pytest.fixture
def email():
    address = f"auth-{uuid.uuid4().hex[:10]}@example.com"
    yield address

    async def cleanup(conn):
        await conn.execute(text("DELETE FROM customer_login_codes WHERE email = :e"), {"e": address})
        await conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": address})

    _run(cleanup)


def test_issue_then_verify_succeeds_once(email):
    code = _run(lambda c: auth.issue_code(c, email))
    assert len(code) == 6 and code.isdigit()
    assert _run(lambda c: auth.verify_code(c, email, code)) == "ok"
    assert _run(lambda c: auth.verify_code(c, email, code)) == "expired"  # consumed


def test_new_code_replaces_old(email):
    old = _run(lambda c: auth.issue_code(c, email))
    new = _run(lambda c: auth.issue_code(c, email))
    if old == new:  # 1-in-a-million collision; the replacement is what matters
        pytest.skip("codes collided")
    assert _run(lambda c: auth.verify_code(c, email, old)) != "ok"
    assert _run(lambda c: auth.verify_code(c, email, new)) == "ok"


def test_wrong_code_five_times_burns(email):
    code = _run(lambda c: auth.issue_code(c, email))
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(5):
        assert _run(lambda c: auth.verify_code(c, email, wrong)) == "wrong"
    assert _run(lambda c: auth.verify_code(c, email, code)) == "expired"  # burnt: ask for a new code


def test_expired_code_rejected(email):
    code = _run(lambda c: auth.issue_code(c, email))
    _run(lambda c: c.execute(
        text("UPDATE customer_login_codes SET expires_at = NOW() - INTERVAL '1 second' WHERE email = :e"), {"e": email}
    ))
    assert _run(lambda c: auth.verify_code(c, email, code)) != "ok"


def test_sixth_send_in_hour_rate_limited(email):
    for _ in range(5):
        _run(lambda c: auth.issue_code(c, email))
    with pytest.raises(auth.CodeRateLimited):
        _run(lambda c: auth.issue_code(c, email))


def test_email_is_normalised(email):
    code = _run(lambda c: auth.issue_code(c, f"  {email.upper()} "))
    assert _run(lambda c: auth.verify_code(c, email, code)) == "ok"


def test_code_hash_is_not_the_code(email):
    code = _run(lambda c: auth.issue_code(c, email))
    stored = _run(lambda c: c.scalar(text("SELECT code_hash FROM customer_login_codes WHERE email = :e"), {"e": email}))
    assert stored != code and len(stored) == 64


def _disable(email):
    async def go(conn):
        await conn.execute(
            text("INSERT INTO users (email, first_name, last_name, status) VALUES (:e, '', '', 'disabled') "
                 "ON CONFLICT (email) DO UPDATE SET status = 'disabled'"),
            {"e": email},
        )
    _run(go)


def test_disabled_account_gets_no_code(email):
    _disable(email)
    assert _run(lambda c: auth.issue_code(c, email)) is None


def test_disabled_account_is_rate_limited_like_any_other(email):
    """Otherwise the 6th request (429 vs 202) reveals which emails are disabled."""
    _disable(email)
    for _ in range(5):
        assert _run(lambda c: auth.issue_code(c, email)) is None
    with pytest.raises(auth.CodeRateLimited):
        _run(lambda c: auth.issue_code(c, email))


def test_session_resolves_until_revoked_or_expired(email):
    token = _run(lambda c: auth.create_session(c, email))
    assert _run(lambda c: auth.resolve_session(c, token))["email"] == email
    assert _run(lambda c: c.scalar(text("SELECT last_login_at IS NOT NULL FROM users WHERE email = :e"), {"e": email}))

    _run(lambda c: auth.revoke_session(c, token))
    assert _run(lambda c: auth.resolve_session(c, token)) is None

    expired = _run(lambda c: auth.create_session(c, email))
    _run(lambda c: c.execute(
        text("UPDATE customer_sessions SET expires_at = NOW() - INTERVAL '1 second' WHERE email = :e"), {"e": email}
    ))
    assert _run(lambda c: auth.resolve_session(c, expired)) is None
    assert _run(lambda c: auth.resolve_session(c, "not-a-token")) is None


def test_revoke_all_sessions(email):
    first = _run(lambda c: auth.create_session(c, email))
    second = _run(lambda c: auth.create_session(c, email))
    _run(lambda c: auth.revoke_all_sessions(c, email))
    assert _run(lambda c: auth.resolve_session(c, first)) is None
    assert _run(lambda c: auth.resolve_session(c, second)) is None


def test_disabled_user_session_does_not_resolve(email):
    token = _run(lambda c: auth.create_session(c, email))
    _disable(email)
    assert _run(lambda c: auth.resolve_session(c, token)) is None


def test_session_token_is_stored_hashed(email):
    token = _run(lambda c: auth.create_session(c, email))
    stored = _run(lambda c: c.scalar(text("SELECT token_hash FROM customer_sessions WHERE email = :e"), {"e": email}))
    assert stored != token and len(stored) == 64


def test_wrong_guesses_are_capped_across_new_codes(email):
    """A new code resets its own 5 attempts, but not the email's daily cap —
    otherwise 5 sends x 5 attempts = 25 guesses an hour, every hour."""
    for _ in range(2):
        code = _run(lambda c: auth.issue_code(c, email))
        wrong = f"{(int(code) + 1) % 10**6:06d}"
        for _ in range(5):
            assert _run(lambda c: auth.verify_code(c, email, wrong)) != "ok"
    fresh = _run(lambda c: auth.issue_code(c, email))
    assert _run(lambda c: auth.verify_code(c, email, fresh)) == "locked"  # locked for the day

    _run(lambda c: c.execute(
        text("UPDATE customer_login_codes SET failures_window_started_at = NOW() - INTERVAL '25 hours' WHERE email = :e"),
        {"e": email},
    ))
    assert _run(lambda c: auth.verify_code(c, email, fresh)) == "ok"  # window passed


def test_first_sign_in_drops_unverified_profile(email):
    """A users row typed by a guest or a dealer before anyone proved they own the
    email must not become the owner's profile."""
    _run(lambda c: c.execute(
        text("""INSERT INTO users (email, first_name, last_name, phone_number, address, city, state, zipcode)
                VALUES (:e, 'Stranger', 'Typed', '4155550000', '9 Other St', 'Oakland', 'CA', '94601')"""),
        {"e": email},
    ))
    _run(lambda c: auth.create_session(c, email))

    async def profile(conn):
        row = (await conn.execute(
            text("SELECT first_name, last_name, phone_number, address, city, state, zipcode FROM users WHERE email = :e"),
            {"e": email},
        )).one()
        return tuple(row)

    assert _run(profile) == ("", "", None, None, None, None, None)


def test_returning_customer_keeps_their_profile(email):
    _run(lambda c: auth.create_session(c, email))
    _run(lambda c: c.execute(text("UPDATE users SET first_name = 'Jane', city = 'SF' WHERE email = :e"), {"e": email}))
    _run(lambda c: auth.create_session(c, email))

    async def profile(conn):
        return tuple((await conn.execute(text("SELECT first_name, city FROM users WHERE email = :e"), {"e": email})).one())

    assert _run(profile) == ("Jane", "SF")
