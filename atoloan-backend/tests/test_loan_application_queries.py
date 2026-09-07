import pytest
from fastapi.testclient import TestClient

import app.main as main


async def _noop() -> None:
    return None


def _disable_db_checks(monkeypatch) -> None:
    monkeypatch.setattr(main, "create_tables", _noop)
    monkeypatch.setattr(main, "test_connection", _noop)


def _mock_engine(monkeypatch, applications: list[dict]) -> None:
    from unittest.mock import AsyncMock, MagicMock

    async def fake_get_applications_for_dealer(conn, dealer_id, limit=200):
        return applications

    monkeypatch.setattr(
        "app.api.routers.loan_applications.get_applications_for_dealer",
        fake_get_applications_for_dealer,
    )
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.begin.return_value = cm
    monkeypatch.setattr("app.core.dependencies.get_engine", lambda: engine)


def test_list_applications_returns_dealer_scoped_rows(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)
    apps = [{"id": 1, "dealer_id": "DLR-000004", "first_name": "Jane"}]
    _mock_engine(monkeypatch, apps)

    resp = TestClient(main.app).get("/dealers/DLR-000004/loan-applications")

    assert resp.status_code == 200
    body = resp.json()
    assert body["dealer_id"] == "DLR-000004"
    assert body["count"] == 1
    assert body["applications"] == apps


def test_list_applications_empty(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)
    _mock_engine(monkeypatch, [])

    resp = TestClient(main.app).get("/dealers/DLR-999999/loan-applications")

    assert resp.status_code == 200
    assert resp.json() == {"dealer_id": "DLR-999999", "applications": [], "count": 0}
