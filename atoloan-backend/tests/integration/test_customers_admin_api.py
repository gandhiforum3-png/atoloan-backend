"""
Admin customer-account routes (service token only — dealer-hub adds the admin
check and audit log). Real sessions against the local Postgres.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db as db
from app.main import app
from tests.integration.conftest import db_available

pytestmark = [
    pytest.mark.skipif(not db_available(), reason="local Postgres not reachable"),
    pytest.mark.anonymous_customer,
]

ADMIN = {"X-Service-Token": "test-service-token"}


def _id(client, email):
    """Admin routes address accounts by id — emails never go in URLs (they'd
    land in access logs)."""
    rows = client.get("/customers", params={"q": email}, headers=ADMIN).json()["customers"]
    return next(row["id"] for row in rows if row["email"] == email)


@pytest.fixture(scope="module")
def client():
    db._engine = None
    with TestClient(app) as c:
        yield c
    db._engine = None


@pytest.fixture
def prefix(client):
    tag = f"adm{uuid.uuid4().hex[:8]}"
    yield tag
    client.cookies.clear()

    async def cleanup():
        async with db.get_engine().begin() as conn:
            await conn.execute(text("DELETE FROM customer_login_codes WHERE email LIKE :p"), {"p": f"{tag}%"})
            await conn.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": f"{tag}%"})

    client.portal.call(cleanup)


def test_requires_service_token(client):
    assert client.get("/customers").status_code == 401
    assert client.post("/customers/1/status", json={"status": "disabled"}).status_code == 401


def test_search_and_pagination(client, prefix, sign_in):
    for n in range(3):
        sign_in(client, f"{prefix}-{n}@example.com")
    client.cookies.clear()
    client.patch(f"/customers/{_id(client, prefix + '-1@example.com')}", json={"first_name": "Rosalind"}, headers=ADMIN)

    everyone = client.get("/customers", params={"q": prefix}, headers=ADMIN).json()
    assert everyone["total"] == 3
    row = everyone["customers"][0]
    assert set(row) == {
        "id", "email", "first_name", "last_name", "phone_number", "status", "created_at", "last_login_at",
        "active_sessions", "applications",
    }
    assert row["active_sessions"] == 1 and row["applications"] == 0

    page = client.get("/customers", params={"q": prefix, "limit": 2, "offset": 2}, headers=ADMIN).json()
    assert page["total"] == 3 and len(page["customers"]) == 1

    by_name = client.get("/customers", params={"q": "rosalind"}, headers=ADMIN).json()
    assert [c["email"] for c in by_name["customers"]] == [f"{prefix}-1@example.com"]
    assert client.get("/customers", params={"q": f"{prefix}_"}, headers=ADMIN).json()["total"] == 0  # _ is literal


def test_detail_has_activity_and_applications(client, prefix, sign_in):
    email = f"{prefix}@example.com"
    sign_in(client, email)
    customer_id = _id(client, email)
    body = client.get(f"/customers/{customer_id}", headers=ADMIN).json()
    assert body["email"] == email and body["status"] == "active"
    assert body["last_login_at"] and body["active_sessions"] == 1
    assert body["applications"] == []
    assert client.get("/customers/999999999", headers=ADMIN).status_code == 404


def test_disable_revokes_sessions_immediately(client, prefix, sign_in):
    email = f"{prefix}@example.com"
    sign_in(client, email)
    customer_id = _id(client, email)
    assert client.get("/me").status_code == 200

    resp = client.post(f"/customers/{customer_id}/status", json={"status": "disabled"}, headers=ADMIN)

    assert resp.status_code == 200 and resp.json()["status"] == "disabled"
    assert client.get("/me").status_code == 401
    assert client.get(f"/customers/{customer_id}", headers=ADMIN).json()["active_sessions"] == 0


def test_enable_restores_sign_in(client, prefix, sign_in):
    email = f"{prefix}@example.com"
    sign_in(client, email)
    customer_id = _id(client, email)
    assert client.post(f"/customers/{customer_id}/status", json={"status": "disabled"}, headers=ADMIN).status_code == 200
    assert client.post(f"/customers/{customer_id}/status", json={"status": "active"}, headers=ADMIN).status_code == 200
    sign_in(client, email)
    customer_id = _id(client, email)
    assert client.get("/me").status_code == 200


def test_status_must_be_known(client, prefix, sign_in):
    email = f"{prefix}@example.com"
    sign_in(client, email)
    customer_id = _id(client, email)
    assert client.post(f"/customers/{customer_id}/status", json={"status": "deleted"}, headers=ADMIN).status_code == 422


def test_patch_returns_before_after(client, prefix, sign_in):
    email = f"{prefix}@example.com"
    sign_in(client, email)
    customer_id = _id(client, email)
    resp = client.patch(f"/customers/{customer_id}", json={"phone_number": "4155550111"}, headers=ADMIN)
    assert resp.status_code == 200
    assert resp.json()["before"]["phone_number"] is None
    assert resp.json()["after"]["phone_number"] == "4155550111"
    assert client.patch("/customers/999999999", json={"city": "X"}, headers=ADMIN).status_code == 404


def test_close(client, prefix, sign_in):
    email = f"{prefix}@example.com"
    sign_in(client, email)
    customer_id = _id(client, email)
    assert client.post(f"/customers/{customer_id}/close", headers=ADMIN).json() == {
        "id": customer_id, "email": email, "status": "closed",
    }
    assert client.get("/me").status_code == 401
    assert client.get(f"/customers/{customer_id}", headers=ADMIN).status_code == 404
    assert client.post(f"/customers/{customer_id}/close", headers=ADMIN).status_code == 404


def test_emails_are_not_accepted_in_urls(client, prefix, sign_in):
    email = f"{prefix}@example.com"
    sign_in(client, email)
    assert client.get(f"/customers/{email}", headers=ADMIN).status_code == 422


def test_status_change_reports_previous_status(client, prefix, sign_in):
    email = f"{prefix}@example.com"
    sign_in(client, email)
    customer_id = _id(client, email)
    body = client.post(f"/customers/{customer_id}/status", json={"status": "disabled"}, headers=ADMIN).json()
    assert body == {"id": customer_id, "email": email, "status": "disabled", "previous_status": "active"}


def test_never_signed_in_rows_are_not_accounts(client, prefix):
    async def guest():
        async with db.get_engine().begin() as conn:
            await conn.execute(
                text("INSERT INTO users (email, first_name, last_name) VALUES (:e, 'Guest', 'Row')"),
                {"e": f"{prefix}-guest@example.com"},
            )

    client.portal.call(guest)
    assert client.get("/customers", params={"q": prefix}, headers=ADMIN).json()["total"] == 0
    assert client.get("/customers", params={"q": f"{prefix}-guest"}, headers=ADMIN).json()["customers"] == []
