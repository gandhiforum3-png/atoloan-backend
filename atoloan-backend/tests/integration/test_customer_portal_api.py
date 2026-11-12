"""
Signed-in customer portal: own applications, profile edits, closing the
account. Real sessions against the local Postgres (skipped when unreachable).
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, text

import app.db as db
from app.main import app
from app.models.loan_application_table import loan_applications_table as la
from tests.integration.conftest import db_available

pytestmark = [
    pytest.mark.skipif(not db_available(), reason="local Postgres not reachable"),
    pytest.mark.anonymous_customer,  # real sessions, not the unit-test stand-in
]


@pytest.fixture(scope="module")
def client():
    db._engine = None
    with TestClient(app) as c:
        yield c
    db._engine = None


@pytest.fixture
def email(client):
    address = f"portal-{uuid.uuid4().hex[:10]}@example.com"
    yield address
    client.cookies.clear()

    async def cleanup():
        async with db.get_engine().begin() as conn:
            await conn.execute(delete(la).where(la.c.email.in_([address, "other-" + address])))
            await conn.execute(text("DELETE FROM customer_login_codes WHERE email = :e"), {"e": address})
            await conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": address})

    client.portal.call(cleanup)


def _seed(client, rows):
    keys = set().union(*rows)
    rows = [{key: row.get(key) for key in keys} for row in rows]  # one executemany needs one key set

    async def go():
        async with db.get_engine().begin() as conn:
            return (await conn.execute(insert(la).returning(la.c.id), rows)).scalars().all()

    return client.portal.call(go)


def test_lists_only_own_applications(client, email, sign_in):
    own_matched, own_review, guest, other = _seed(client, [
        {"first_name": "J", "last_name": "D", "email": email, "customer_email": email, "bank_id": 1,
         "bank_name": "Alpha CU", "interest_rate": "5.49%", "term_in_months": 60, "program_name": "Used",
         "prequal_score": 712, "prequal_tier": "B", "drivers_license_key": "k/dl.jpg"},
        {"first_name": "J", "last_name": "D", "email": email, "customer_email": email},
        {"first_name": "J", "last_name": "D", "email": email, "customer_email": None},  # guest pull, same email
        {"first_name": "O", "last_name": "P", "email": "other-" + email, "customer_email": "other-" + email},
    ])
    sign_in(client, email)

    apps = client.get("/me/applications").json()

    assert [a["id"] for a in apps] == [own_review, own_matched]  # newest first
    matched = apps[1]
    assert matched["status"] == "matched"
    assert matched["bank_name"] == "Alpha CU" and matched["interest_rate"] == "5.49%" and matched["term_in_months"] == 60
    assert matched["documents"] == {"drivers_license": True, "paycheck": False}
    assert apps[0]["status"] == "in_review"
    assert guest not in [a["id"] for a in apps] and other not in [a["id"] for a in apps]


def test_no_score_fields_in_response(client, email, sign_in):
    _seed(client, [{"first_name": "J", "last_name": "D", "email": email, "customer_email": email, "prequal_score": 700}])
    sign_in(client, email)
    app_row = client.get("/me/applications").json()[0]
    assert not {"prequal_score", "prequal_tier", "score", "tier", "credit_score", "prequal_raw"} & set(app_row)


def test_applications_require_session(client):
    client.cookies.clear()
    assert client.get("/me/applications").status_code == 401


def test_patch_validates_and_updates(client, email, sign_in):
    sign_in(client, email)

    bad = client.patch("/me", json={"phone_number": "555", "state": "California", "zipcode": "9410"})
    assert bad.status_code == 422

    resp = client.patch("/me", json={"first_name": " Jane ", "phone_number": "4155550100", "state": "CA", "zipcode": "94102"})
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Jane"
    assert client.get("/me").json()["phone_number"] == "4155550100"


def test_patch_cannot_change_email(client, email, sign_in):
    sign_in(client, email)
    resp = client.patch("/me", json={"email": "taken@example.com", "city": "Oakland"})
    assert resp.status_code == 200
    assert resp.json()["email"] == email
    assert resp.json()["city"] == "Oakland"


def test_close_requires_matching_email(client, email, sign_in):
    sign_in(client, email)
    resp = client.post("/me/close", json={"confirm_email": "someone@example.com"})
    assert resp.status_code == 400
    assert client.get("/me").status_code == 200


def test_close_deletes_account_keeps_applications(client, email, sign_in):
    (app_id,) = _seed(client, [{"first_name": "J", "last_name": "D", "email": email, "customer_email": email}])
    sign_in(client, email)
    client.post("/auth/request-code", json={"email": email})  # a pending code that must go too

    resp = client.post("/me/close", json={"confirm_email": email.upper()})

    assert resp.status_code == 200 and resp.json() == {"status": "closed"}
    assert client.get("/me").status_code == 401

    async def counts():
        async with db.get_engine().connect() as conn:
            return {
                table: await conn.scalar(text(f"SELECT COUNT(*) FROM {table} WHERE email = :e"), {"e": email})
                for table in ("users", "customer_sessions", "customer_login_codes")
            } | {"applications": await conn.scalar(text("SELECT COUNT(*) FROM loan_applications WHERE id = :i"), {"i": app_id})}

    assert client.portal.call(counts) == {"users": 0, "customer_sessions": 0, "customer_login_codes": 0, "applications": 1}


def test_same_email_can_sign_up_after_close(client, email, sign_in):
    sign_in(client, email)
    assert client.post("/me/close", json={"confirm_email": email}).status_code == 200
    sign_in(client, email)
    assert client.get("/me").json()["email"] == email
