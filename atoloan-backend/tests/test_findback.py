import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.models.prequal_result import PrequalResult

# Load .env so real SEVENCREDIT_* values are available when this file is run
# on its own (e.g. `pytest tests/test_findback.py`), matching the pattern in
# tests/integration/conftest.py — otherwise test_findback_integration silently
# skips instead of actually running.
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if _ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE, override=False)


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
def test_findback_integration(monkeypatch, caplog) -> None:
    caplog.set_level("INFO")
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

    print(f"\n{'=' * 70}")
    print(f"findback integration — HTTP status: {resp.status_code}")
    print(f"findback integration — response headers: {dict(resp.headers)}")

    body = resp.json()
    print(f"findback integration — full response body:\n{json.dumps(body, indent=2)}")

    prequal = body.get("prequal") or {}
    raw_xml = prequal.get("raw_xml")
    if raw_xml:
        print(f"findback integration — raw 700Credit XML:\n{raw_xml}")

    if resp.status_code != 200:
        print(f"findback integration — error detail: {body.get('detail')}")
        # The router swallows the real 700Credit error body into a generic
        # 502 — pull the actual XML response back out of the logs it was
        # captured into (app.integrations.seven_hundred logs it on failure).
        for record in caplog.records:
            if record.name == "app.integrations.seven_hundred":
                print(f"findback integration — actual 700Credit gateway response:\n{record.getMessage()}")
    print(f"{'=' * 70}\n")

    print("findback integration response:", _human_readable(body))
    assert resp.status_code == 200
    assert "prequal" in body


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
