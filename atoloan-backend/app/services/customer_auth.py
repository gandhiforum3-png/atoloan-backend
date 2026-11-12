"""
Customer sign-in: emailed one-time codes and server-side sessions.

Codes: 6 digits, 10 minutes, 5 wrong attempts burn it, a new code replaces the
old one, at most 5 sends per email per hour, and at most 10 wrong guesses per
email per 24h across all codes (so new codes can't buy fresh guesses). Stored as an HMAC keyed by
CUSTOMER_AUTH_SECRET so a database leak can't be brute-forced offline.
Sessions: random token in the cookie, only its SHA-256 in the database.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings

CODE_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(hours=12)
MAX_ATTEMPTS = 5
MAX_SENDS_PER_HOUR = 5
MAX_FAILURES_PER_DAY = 10
_DEV_KEY = b"local-dev-only-customer-auth-key"

PROFILE_COLUMNS = ("email", "first_name", "last_name", "phone_number", "address", "city", "state", "zipcode")


class CodeRateLimited(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _key() -> bytes:
    settings = get_settings()
    if settings.customer_auth_secret:
        return settings.customer_auth_secret.encode()
    if settings.app_env in ("", "local"):
        return _DEV_KEY
    raise RuntimeError("CUSTOMER_AUTH_SECRET is not set")


def _code_hash(email: str, code: str) -> str:
    return hmac.new(_key(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _is_disabled(conn: AsyncConnection, email: str) -> bool:
    status = await conn.scalar(text("SELECT status FROM users WHERE email = :e"), {"e": email})
    return status == "disabled"


async def issue_code(conn: AsyncConnection, email: str) -> str | None:
    """New code for `email` (replacing any pending one), or None for a disabled
    account. Disabled accounts go through the same send cap — a different
    answer on the 6th request would reveal which emails are disabled."""
    email = normalize_email(email)
    code = f"{secrets.randbelow(10**6):06d}"
    # One statement: the WHERE refuses the update (no row returned) once the
    # hour's sends are used up, so the pending code is left untouched.
    row = (
        await conn.execute(
            text("""
                INSERT INTO customer_login_codes (email, code_hash, expires_at, attempts, sends, window_started_at)
                VALUES (:e, :h, NOW() + :ttl, 0, 1, NOW())
                ON CONFLICT (email) DO UPDATE SET
                    code_hash = EXCLUDED.code_hash,
                    expires_at = EXCLUDED.expires_at,
                    attempts = 0,
                    sends = CASE WHEN customer_login_codes.window_started_at < NOW() - INTERVAL '1 hour'
                                 THEN 1 ELSE customer_login_codes.sends + 1 END,
                    window_started_at = CASE WHEN customer_login_codes.window_started_at < NOW() - INTERVAL '1 hour'
                                             THEN NOW() ELSE customer_login_codes.window_started_at END
                WHERE customer_login_codes.window_started_at < NOW() - INTERVAL '1 hour'
                   OR customer_login_codes.sends < :max_sends
                RETURNING sends
            """),
            {"e": email, "h": _code_hash(email, code), "ttl": CODE_TTL, "max_sends": MAX_SENDS_PER_HOUR},
        )
    ).first()
    if row is None:
        raise CodeRateLimited(email)
    # verify_code refuses disabled accounts, so a code stored for one is inert
    return None if await _is_disabled(conn, email) else code


VerifyResult = Literal["ok", "wrong", "expired", "locked"]


async def verify_code(conn: AsyncConnection, email: str, code: str) -> VerifyResult:
    """"ok" once for the right, live code (it is consumed). "wrong" counts toward
    the attempt limits. "expired": no live code (none, used, timed out, 5 misses
    burnt it, or the account is disabled) — the customer needs a new one.
    "locked": 10 wrong guesses in 24h across codes."""
    email = normalize_email(email)
    row = (
        await conn.execute(
            text("""
                SELECT code_hash, attempts, expires_at > NOW() AS live,
                       failures_window_started_at > NOW() - INTERVAL '1 day' AND failures >= :max_failures AS locked
                FROM customer_login_codes WHERE email = :e FOR UPDATE
            """),
            {"e": email, "max_failures": MAX_FAILURES_PER_DAY},
        )
    ).mappings().first()
    if row is not None and row["locked"]:
        return "locked"
    if row is None or not row["live"] or row["attempts"] >= MAX_ATTEMPTS or await _is_disabled(conn, email):
        return "expired"
    if hmac.compare_digest(row["code_hash"], _code_hash(email, code.strip())):
        await conn.execute(text("DELETE FROM customer_login_codes WHERE email = :e"), {"e": email})
        return "ok"
    await conn.execute(
        text("""
            UPDATE customer_login_codes SET
                attempts = attempts + 1,
                failures = CASE WHEN failures_window_started_at < NOW() - INTERVAL '1 day' THEN 1 ELSE failures + 1 END,
                failures_window_started_at = CASE WHEN failures_window_started_at < NOW() - INTERVAL '1 day'
                                                  THEN NOW() ELSE failures_window_started_at END
            WHERE email = :e
        """),
        {"e": email},
    )
    return "wrong"


async def create_session(conn: AsyncConnection, email: str) -> str:
    """Sign in a verified email: creates the account on first sign-in. A row
    that existed before anyone proved they own the email (typed by a guest or a
    dealer) keeps nothing it was given — its contact details start empty."""
    email = normalize_email(email)
    first_sign_in = "users.last_login_at IS NULL"
    await conn.execute(
        text(f"""
            INSERT INTO users (email, first_name, last_name, last_login_at)
            VALUES (:e, '', '', NOW())
            ON CONFLICT (email) DO UPDATE SET
                first_name   = CASE WHEN {first_sign_in} THEN '' ELSE users.first_name END,
                last_name    = CASE WHEN {first_sign_in} THEN '' ELSE users.last_name END,
                phone_number = CASE WHEN {first_sign_in} THEN NULL ELSE users.phone_number END,
                address      = CASE WHEN {first_sign_in} THEN NULL ELSE users.address END,
                city         = CASE WHEN {first_sign_in} THEN NULL ELSE users.city END,
                state        = CASE WHEN {first_sign_in} THEN NULL ELSE users.state END,
                zipcode      = CASE WHEN {first_sign_in} THEN NULL ELSE users.zipcode END,
                last_login_at = NOW()
        """),
        {"e": email},
    )
    token = secrets.token_urlsafe(32)
    await conn.execute(
        text("INSERT INTO customer_sessions (token_hash, email, expires_at) VALUES (:h, :e, NOW() + :ttl)"),
        {"h": _token_hash(token), "e": email, "ttl": SESSION_TTL},
    )
    return token


async def resolve_session(conn: AsyncConnection, token: str) -> dict | None:
    """The signed-in customer's profile, or None (unknown, revoked, expired or disabled)."""
    row = (
        await conn.execute(
            text(f"""
                SELECT {", ".join("u." + c for c in PROFILE_COLUMNS)}
                FROM customer_sessions s JOIN users u ON u.email = s.email
                WHERE s.token_hash = :h AND s.revoked_at IS NULL AND s.expires_at > NOW()
                  AND u.status = 'active'
            """),
            {"h": _token_hash(token)},
        )
    ).mappings().first()
    return dict(row) if row else None


async def revoke_session(conn: AsyncConnection, token: str) -> None:
    await conn.execute(
        text("UPDATE customer_sessions SET revoked_at = NOW() WHERE token_hash = :h AND revoked_at IS NULL"),
        {"h": _token_hash(token)},
    )


async def revoke_all_sessions(conn: AsyncConnection, email: str) -> None:
    await conn.execute(
        text("UPDATE customer_sessions SET revoked_at = NOW() WHERE email = :e AND revoked_at IS NULL"),
        {"e": normalize_email(email)},
    )
