import pytest
from fastapi.testclient import TestClient

import app.main as main


async def _noop() -> None:
    return None


def _disable_db_checks(monkeypatch) -> None:
    monkeypatch.setattr(main, "create_tables", _noop)
    monkeypatch.setattr(main, "test_connection", _noop)


def _mock_conn(monkeypatch) -> None:
    """Make get_conn() a no-op async context manager — the query functions
    themselves are stubbed per-test, so no DB is needed."""
    from unittest.mock import AsyncMock, MagicMock

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.begin.return_value = cm
    monkeypatch.setattr("app.core.dependencies.get_engine", lambda: engine)


def _mock_list(monkeypatch, page: dict) -> None:
    async def fake(conn, dealer_id, limit=50, offset=0):
        return page

    monkeypatch.setattr("app.api.routers.loan_applications.get_applications_for_dealer", fake)


def test_list_applications_returns_dealer_scoped_rows(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)
    _mock_conn(monkeypatch)
    apps = [{"id": 1, "dealer_id": "DLR-000004", "first_name": "Jane"}]
    _mock_list(monkeypatch, {"applications": apps, "total": 1})

    resp = TestClient(main.app).get("/dealers/DLR-000004/loan-applications")

    assert resp.status_code == 200
    assert resp.json() == {"dealer_id": "DLR-000004", "applications": apps, "total": 1}


def test_list_applications_empty(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)
    _mock_conn(monkeypatch)
    _mock_list(monkeypatch, {"applications": [], "total": 0})

    resp = TestClient(main.app).get("/dealers/DLR-999999/loan-applications")

    assert resp.status_code == 200
    assert resp.json() == {"dealer_id": "DLR-999999", "applications": [], "total": 0}


def test_list_applications_forwards_pagination(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)
    _mock_conn(monkeypatch)
    seen = {}

    async def fake(conn, dealer_id, limit=50, offset=0):
        seen.update(limit=limit, offset=offset)
        return {"applications": [], "total": 0}

    monkeypatch.setattr("app.api.routers.loan_applications.get_applications_for_dealer", fake)

    TestClient(main.app).get("/dealers/DLR-000004/loan-applications?limit=5&offset=10")

    assert seen == {"limit": 5, "offset": 10}


def test_summary_returns_counts(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)
    _mock_conn(monkeypatch)
    summary = {"total": 3, "matched": 2, "unmatched": 1, "last_7_days": 3}

    async def fake(conn, dealer_id):
        return summary

    monkeypatch.setattr("app.api.routers.loan_applications.get_summary_for_dealer", fake)

    resp = TestClient(main.app).get("/dealers/DLR-000004/loan-applications/summary")

    assert resp.status_code == 200
    assert resp.json() == summary
