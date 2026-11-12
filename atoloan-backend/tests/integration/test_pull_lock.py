"""
One credit pull at a time per signed-in account: while a pull holds the
account's advisory lock, a parallel pull is refused — otherwise N parallel
requests all pass the daily-cap check before any of them saves its row.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db as db
from app.api.routers import findback as findback_module
from app.main import app
from app.models.prequal_result import PrequalResult
from tests.integration.conftest import db_available

pytestmark = [pytest.mark.skipif(not db_available(), reason="local Postgres not reachable"), pytest.mark.real_pull_lock]

PAYLOAD = {
    "first_name": "Jane", "last_name": "Doe", "email": "jane@example.com",
    "address": "1 Main St", "city": "SF", "state": "CA", "zip_code": "94102", "consent": True,
}


def test_parallel_pull_for_same_account_is_refused(monkeypatch):
    calls = []

    class FakeCredit:
        def __init__(self, **_):
            pass

        def send_prequalify(self, **_):
            calls.append(1)
            return PrequalResult(raw_xml="<x/>", result_code="0")

    monkeypatch.setattr(findback_module, "SevenHundredCreditClient", FakeCredit)
    monkeypatch.setattr(findback_module, "save_findback_result", AsyncMock(return_value=9))

    db._engine = None
    with TestClient(app) as client:
        holder = {}

        async def hold():  # another in-flight pull for jane@example.com
            holder["conn"] = await db.get_engine().connect()
            await holder["conn"].execute(
                text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": "credit-pull:jane@example.com"}
            )

        async def release():
            await holder["conn"].execute(
                text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": "credit-pull:jane@example.com"}
            )
            await holder["conn"].close()

        client.portal.call(hold)
        try:
            blocked = client.post("/findback", json=PAYLOAD)
        finally:
            client.portal.call(release)
        assert blocked.status_code == 429
        assert "already running" in blocked.json()["detail"]
        assert calls == []

        assert client.post("/findback", json=PAYLOAD).status_code == 200
        assert calls == [1]
    db._engine = None
