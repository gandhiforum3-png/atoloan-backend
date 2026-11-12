"""
GET /dealers/{id}/loan-applications and GET /loan-applications against the
local Postgres (skipped when it isn't reachable).
"""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

import app.db as db
from app.main import app
from app.models.loan_application_table import loan_applications_table as la

HEADERS = {"X-Service-Token": "test-service-token"}
DEALER = f"T-{uuid.uuid4().hex[:8]}"


def _db_available() -> bool:
    async def probe():
        try:
            await db.test_connection()
            return True
        except Exception:
            return False
        finally:
            await db.get_engine().dispose()
            db._engine = None

    return asyncio.run(probe())


pytestmark = pytest.mark.skipif(not _db_available(), reason="local Postgres not reachable")


@pytest.fixture(scope="module")
def client():
    db._engine = None  # bind the engine to this TestClient's event loop
    with TestClient(app) as c:
        c.portal.call(_seed)
        yield c
        c.portal.call(_cleanup)
    db._engine = None


async def _seed():
    async with db.get_engine().begin() as conn:
        await conn.execute(
            insert(la),
            [
                {"first_name": "Own", "last_name": f"App{i}", "email": f"own{i}@example.com", "dealer_id": DEALER,
                 "prequal_raw": {"token": "secret"}, "upload_token_hash": "h" * 64, "client_ip": "203.0.113.1"}
                for i in range(3)
            ]
            + [{"first_name": "Other", "last_name": "Dealer", "email": "other@example.com", "dealer_id": DEALER + "x",
                "prequal_raw": None, "upload_token_hash": None, "client_ip": None}],
        )


async def _cleanup():
    async with db.get_engine().begin() as conn:
        await conn.execute(delete(la).where(la.c.dealer_id.in_([DEALER, DEALER + "x"])))


def test_requires_service_token(client):
    assert client.get(f"/dealers/{DEALER}/loan-applications").status_code == 401
    assert client.get("/loan-applications").status_code == 401


def test_dealer_sees_only_their_applications(client):
    body = client.get(f"/dealers/{DEALER}/loan-applications", headers=HEADERS).json()
    assert body["total"] == 3
    assert {a["dealer_id"] for a in body["applications"]} == {DEALER}


def test_sensitive_columns_never_returned(client):
    app_row = client.get(f"/dealers/{DEALER}/loan-applications", headers=HEADERS).json()["applications"][0]
    assert not {"prequal_raw", "upload_token_hash", "client_ip"} & set(app_row)


def test_pagination(client):
    page = client.get(f"/dealers/{DEALER}/loan-applications?limit=2&offset=2", headers=HEADERS).json()
    assert page["total"] == 3
    assert len(page["applications"]) == 1


def test_admin_listing_filters_by_dealer(client):
    body = client.get(f"/loan-applications?dealer_id={DEALER}x", headers=HEADERS).json()
    assert body["total"] == 1
    assert body["applications"][0]["first_name"] == "Other"


def test_summary_counts_all_rows_not_one_page(client):
    body = client.get(f"/dealers/{DEALER}/loan-applications/summary", headers=HEADERS).json()
    assert body == {"total": 3, "matched": 0, "unmatched": 3, "last_7_days": 3}
    assert client.get(f"/loan-applications/summary?dealer_id={DEALER}x", headers=HEADERS).json()["total"] == 1


def test_admin_customer_search(client):
    def total(q):
        return client.get("/loan-applications", params={"q": q, "dealer_id": DEALER}, headers=HEADERS).json()["total"]

    assert total("own1@EXAMPLE") == 1  # email, case-insensitive
    assert total("Own App2") == 1  # full name
    assert total("app") == 3  # partial last name
    assert total("own_") == 0  # _ is literal, not a one-char wildcard (would match own0..own2)
    summary = client.get("/loan-applications/summary", params={"q": "own0", "dealer_id": DEALER}, headers=HEADERS).json()
    assert summary["total"] == 1
