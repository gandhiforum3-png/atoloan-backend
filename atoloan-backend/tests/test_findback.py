import os
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.models.prequal_result import PrequalResult


async def _noop() -> None:
    return None


def _client() -> TestClient:
    return TestClient(main.app)


def _disable_db_checks(monkeypatch) -> None:
    monkeypatch.setattr(main, "create_tables", _noop)
    monkeypatch.setattr(main, "test_connection", _noop)


def test_findback_missing_fields(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)
    client = _client()

    resp = client.post("/findback", json={"first_name": "A"})

    assert resp.status_code == 400
    assert "missing required fields" in resp.json()["detail"]


def test_findback_success(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)

    class DummyClient:
        def __init__(self, **_kw):
            pass

        def send_prequalify(self, **_kwargs) -> PrequalResult:
            return PrequalResult(raw_xml="<xml/>", result_code="0", tier="A")

    monkeypatch.setattr("app.api.routers.findback.SevenHundredCreditClient", DummyClient)

    client = _client()
    payload = {
        "first_name": "Blackwell",
        "last_name": "Phillip",
        "email": "blackwell@example.com",
        "address": "800 Rice Valley N",
        "city": "Tuscaloosa",
        "state": "AL",
        "zip_code": "80134",
    }

    # Patch save so it doesn't hit the DB
    monkeypatch.setattr(
        "app.api.routers.findback.save_findback_result",
        AsyncMock(return_value=1),
    )

    resp = client.post("/findback", json=payload)

    print("findback response:", _human_readable(resp.json()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["prequal"]["result_code"] == "0"
    assert body["prequal"]["raw_xml"] == "<xml/>"


def test_findback_missing_credentials(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)

    class DummyFactory:
        def __init__(self, **_kw):
            raise ValueError("missing credentials")

    monkeypatch.setattr("app.api.routers.findback.SevenHundredCreditClient", DummyFactory)

    client = _client()
    payload = {
        "first_name": "Blackwell",
        "last_name": "Phillip",
        "email": "blackwell@example.com",
        "address": "800 Rice Valley N",
        "city": "Tuscaloosa",
        "state": "AL",
        "zip_code": "80134",
    }

    resp = client.post("/findback", json=payload)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "missing credentials"


@pytest.mark.skipif(
    not os.getenv("SEVENCREDIT_ACCOUNT") or not os.getenv("SEVENCREDIT_PASSWORD"),
    reason="Missing 700Credit credentials",
)
def test_findback_integration(monkeypatch) -> None:
    _disable_db_checks(monkeypatch)
    client = _client()
    payload = {
        "first_name": "Blackwell",
        "last_name": "Phillip",
        "email": "blackwell@example.com",
        "address": "800 Rice Valley N",
        "city": "Tuscaloosa",
        "state": "AL",
        "zip_code": "80134",
        "bureau": "TU",
        "app_modified": False,
    }

    monkeypatch.setattr(
        "app.api.routers.findback.save_findback_result",
        AsyncMock(return_value=1),
    )

    resp = client.post("/findback", json=payload)

    print("findback integration response:", _human_readable(resp.json()))
    assert resp.status_code == 200
    assert "prequal" in resp.json()


def _human_readable(body: dict) -> str:
    prequal = body.get("prequal", {})
    code = prequal.get("result_code") or "unknown"
    desc = prequal.get("result_description") or "no description"
    score = prequal.get("score")
    tier = prequal.get("tier")
    parts = [f"code={code}", f"desc={desc}"]
    if score is not None:
        parts.append(f"score={score}")
    if tier:
        parts.append(f"tier={tier}")
    return "; ".join(parts)
