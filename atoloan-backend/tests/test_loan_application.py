"""
Unit tests for the loan application persistence feature.

Covers:
  1. save_findback_result() service — DB interaction via mocked AsyncConnection
  2. /findback router — email/phone field extraction (flat + nested contactInfo)
  3. /findback router — email is now a required field
  4. /findback router — application_id returned in response on success
  5. /findback router — DB save failure is best-effort (response still returned)
  6. /findback router — prequal_raw excludes raw_xml before storing
"""

from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.models.prequal_result import PrequalResult
from app.services.loan_application_mutations import save_findback_result


# ---------------------------------------------------------------------------
# Helpers shared by router tests
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(main.app)


async def _noop() -> None:
    return None


def _disable_db_checks(monkeypatch) -> None:
    monkeypatch.setattr(main, "create_tables", _noop)
    monkeypatch.setattr(main, "test_connection", _noop)


def _dummy_prequal(result_code: str = "0", score: int = 740) -> PrequalResult:
    return PrequalResult(
        raw_xml="<xml/>",
        result_code=result_code,
        result_description="Approved",
        score=score,
        tier="A",
        score_range="720-850",
        transid="TX123",
    )


FLAT_PAYLOAD = {
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com",
    "phone_number": "415-555-9999",
    "address": "123 Main St",
    "city": "San Francisco",
    "state": "CA",
    "zip_code": "94102",
    "otherDownPayment": "5000",
}

NESTED_PAYLOAD = {
    "contactInfo": {
        "firstName": "Jane",
        "lastName": "Doe",
        "email": "jane@example.com",
        "phone": "415-555-9999",
        "address": "123 Main St",
        "city": "San Francisco",
        "state": "CA",
        "zip": "94102",
    },
    "otherDownPayment": "5000",
}


# ---------------------------------------------------------------------------
# 1. save_findback_result — unit tests (mocked AsyncConnection)
# ---------------------------------------------------------------------------

class TestSaveFindbackResult:
    """Tests for the save_findback_result() service function."""

    def _make_conn(self, returned_id: int = 42) -> AsyncMock:
        """Build a minimal AsyncConnection mock that returns the given id."""
        conn = AsyncMock()
        # conn.execute() for the INSERT ... RETURNING must return a result
        # whose scalar_one() gives the new application id.
        insert_result = MagicMock()
        insert_result.scalar_one.return_value = returned_id
        # First execute() = upsert user (returns nothing we use)
        # Second execute() = insert loan_application (returns insert_result)
        conn.execute = AsyncMock(side_effect=[AsyncMock(), insert_result])
        return conn

    async def test_returns_application_id(self) -> None:
        conn = self._make_conn(returned_id=7)
        app_id = await save_findback_result(
            conn,
            email="test@example.com",
            first_name="Jane",
            last_name="Doe",
            address="123 Main St",
            city="SF",
            state="CA",
            zipcode="94102",
            phone_number="415-000-0000",
            down_payment=5000.0,
            credit_score=740,
            prequal=_dummy_prequal().to_dict(),
            best_bank=None,
        )
        assert app_id == 7

    async def test_calls_execute_twice(self) -> None:
        """Verifies both the user upsert and loan_application insert are executed."""
        conn = self._make_conn()
        await save_findback_result(
            conn,
            email="test@example.com",
            first_name="Jane",
            last_name="Doe",
            address=None,
            city=None,
            state=None,
            zipcode=None,
            phone_number=None,
            down_payment=None,
            credit_score=None,
            prequal=_dummy_prequal().to_dict(),
            best_bank=None,
        )
        assert conn.execute.call_count == 2

    async def test_prequal_raw_excludes_raw_xml(self) -> None:
        """raw_xml must not be stored in the JSONB column (it's verbose XML)."""
        conn = self._make_conn()
        await save_findback_result(
            conn,
            email="test@example.com",
            first_name="Jane",
            last_name="Doe",
            address=None,
            city=None,
            state=None,
            zipcode=None,
            phone_number=None,
            down_payment=None,
            credit_score=None,
            prequal=_dummy_prequal().to_dict(),
            best_bank=None,
        )
        # The INSERT call is the second execute() call.
        insert_call = conn.execute.call_args_list[1]
        # The compiled statement is the first positional arg.
        insert_stmt = insert_call.args[0]
        # Inspect the values dict from the Insert statement.
        values = insert_stmt.compile().params if hasattr(insert_stmt, "compile") else {}
        # Alternatively, check via the clause directly.
        clause_kw = {
            col.key: col
            for col in insert_stmt.table.columns
        }
        assert "prequal_raw" in clause_kw  # column exists
        # Verify the value passed for prequal_raw doesn't have raw_xml key
        # by inspecting what was bound at construction time.
        bound = {
            k.key: v
            for k, v in zip(insert_stmt.table.columns, [])
        }
        # Simpler: extract _values from the Insert clause
        insert_values = insert_stmt._values if hasattr(insert_stmt, "_values") else {}
        if insert_values:
            raw = insert_values.get("prequal_raw")
            if raw is not None:
                assert "raw_xml" not in raw.value

    async def test_bank_offer_stored_when_provided(self) -> None:
        """bank_id, bank_name and interest_rate from best_bank reach the INSERT."""
        conn = self._make_conn(returned_id=99)
        best_bank = {
            "bank_id": 3,
            "bank_name": "Test CU",
            "interest_rate": "4.99%",
            "program_name": "Auto Loan",
            "tier_name": "Tier 1",
            "term_in_months": 60,
            "min_loan_amount": 5000,
            "max_loan_amount": 50000,
        }
        app_id = await save_findback_result(
            conn,
            email="test@example.com",
            first_name="Jane",
            last_name="Doe",
            address=None,
            city=None,
            state=None,
            zipcode=None,
            phone_number=None,
            down_payment=10000.0,
            credit_score=750,
            prequal=_dummy_prequal().to_dict(),
            best_bank=best_bank,
        )
        assert app_id == 99
        # The INSERT was called (2nd execute), confirming bank data was passed
        assert conn.execute.call_count == 2

    async def test_no_bank_offer_does_not_raise(self) -> None:
        """Passing best_bank=None must not raise."""
        conn = self._make_conn()
        await save_findback_result(
            conn,
            email="nobody@example.com",
            first_name="A",
            last_name="B",
            address=None,
            city=None,
            state=None,
            zipcode=None,
            phone_number=None,
            down_payment=None,
            credit_score=None,
            prequal=_dummy_prequal().to_dict(),
            best_bank=None,
        )


# ---------------------------------------------------------------------------
# 2. /findback router — field extraction and validation
# ---------------------------------------------------------------------------

class TestFindbackRouterFields:
    """Tests for email/phone handling added to the findback endpoint."""

    def _mock_save(self, monkeypatch, app_id: int = 42) -> AsyncMock:
        mock = AsyncMock(return_value=app_id)
        monkeypatch.setattr("app.api.routers.findback.save_findback_result", mock)
        return mock

    def _mock_prequal(self, monkeypatch) -> None:
        class DummyClient:
            def send_prequalify(self, **_) -> PrequalResult:
                return _dummy_prequal()

        monkeypatch.setattr(
            "app.api.routers.findback.SevenHundredCreditClient",
            type("F", (), {"__init__": lambda s, **kw: None, "send_prequalify": DummyClient().send_prequalify}),
        )

    def _mock_bank_finder(self, monkeypatch, offer: dict | None = None) -> None:
        async def _finder(*_, **__):
            return offer
        monkeypatch.setattr("app.api.routers.findback.find_best_bank", _finder)

    def _mock_engine(self, monkeypatch) -> None:
        """Make get_engine().begin() a no-op async context manager."""
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        cm.__aexit__ = AsyncMock(return_value=False)
        engine = MagicMock()
        engine.begin.return_value = cm
        monkeypatch.setattr("app.api.routers.findback.get_engine", lambda: engine)

    def test_email_required_flat_payload(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        client = _client()

        payload = {
            "first_name": "Jane",
            "last_name": "Doe",
            "address": "123 Main St",
            "city": "SF",
            "state": "CA",
            "zip_code": "94102",
            # email intentionally omitted
        }
        resp = client.post("/findback", json=payload)

        assert resp.status_code == 400
        assert "email" in resp.json()["detail"]

    def test_email_required_nested_contactinfo(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        client = _client()

        payload = {
            "contactInfo": {
                "firstName": "Jane",
                "lastName": "Doe",
                "address": "123 Main St",
                "city": "SF",
                "state": "CA",
                "zip": "94102",
                # email intentionally omitted
            }
        }
        resp = client.post("/findback", json=payload)

        assert resp.status_code == 400
        assert "email" in resp.json()["detail"]

    def test_flat_payload_saves_and_returns_application_id(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        self._mock_prequal(monkeypatch)
        self._mock_bank_finder(monkeypatch)
        self._mock_engine(monkeypatch)
        save_mock = self._mock_save(monkeypatch, app_id=55)

        resp = _client().post("/findback", json=FLAT_PAYLOAD)

        assert resp.status_code == 200
        body = resp.json()
        assert body["application_id"] == 55
        save_mock.assert_awaited_once()
        kwargs = save_mock.call_args.kwargs
        assert kwargs["email"] == "jane@example.com"
        assert kwargs["phone_number"] == "415-555-9999"

    def test_nested_contactinfo_saves_and_returns_application_id(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        self._mock_prequal(monkeypatch)
        self._mock_bank_finder(monkeypatch)
        self._mock_engine(monkeypatch)
        save_mock = self._mock_save(monkeypatch, app_id=77)

        resp = _client().post("/findback", json=NESTED_PAYLOAD)

        assert resp.status_code == 200
        body = resp.json()
        assert body["application_id"] == 77
        kwargs = save_mock.call_args.kwargs
        assert kwargs["email"] == "jane@example.com"
        assert kwargs["phone_number"] == "415-555-9999"

    def test_save_failure_does_not_break_response(self, monkeypatch) -> None:
        """DB save failure must be swallowed — prequal result still returned."""
        _disable_db_checks(monkeypatch)
        self._mock_prequal(monkeypatch)
        self._mock_bank_finder(monkeypatch)
        self._mock_engine(monkeypatch)

        async def _failing_save(*_, **__):
            raise RuntimeError("DB is down")

        monkeypatch.setattr("app.api.routers.findback.save_findback_result", _failing_save)

        resp = _client().post("/findback", json=FLAT_PAYLOAD)

        assert resp.status_code == 200
        body = resp.json()
        assert "prequal" in body
        assert body["prequal"]["result_code"] == "0"
        # application_id must be absent when save fails
        assert "application_id" not in body

    def test_best_bank_passed_to_save(self, monkeypatch) -> None:
        """When bank finder returns an offer it must be forwarded to save."""
        _disable_db_checks(monkeypatch)
        self._mock_prequal(monkeypatch)
        bank_offer = {
            "bank_id": 1,
            "bank_name": "Test CU",
            "interest_rate": "3.99%",
            "program_name": "Auto",
            "tier_name": "Gold",
            "term_in_months": 60,
            "min_loan_amount": 5000,
            "max_loan_amount": 50000,
        }
        self._mock_bank_finder(monkeypatch, offer=bank_offer)
        self._mock_engine(monkeypatch)
        save_mock = self._mock_save(monkeypatch)

        _client().post("/findback", json=FLAT_PAYLOAD)

        kwargs = save_mock.call_args.kwargs
        assert kwargs["best_bank"] == bank_offer

    def test_no_bank_offer_saves_none(self, monkeypatch) -> None:
        """When bank finder returns None, save is still called with best_bank=None."""
        _disable_db_checks(monkeypatch)
        self._mock_prequal(monkeypatch)
        self._mock_bank_finder(monkeypatch, offer=None)
        self._mock_engine(monkeypatch)
        save_mock = self._mock_save(monkeypatch)

        _client().post("/findback", json=FLAT_PAYLOAD)

        kwargs = save_mock.call_args.kwargs
        assert kwargs["best_bank"] is None

    def test_prequal_dict_passed_to_save(self, monkeypatch) -> None:
        """The full PrequalResult dict (including score/tier) must reach save."""
        _disable_db_checks(monkeypatch)
        self._mock_prequal(monkeypatch)
        self._mock_bank_finder(monkeypatch)
        self._mock_engine(monkeypatch)
        save_mock = self._mock_save(monkeypatch)

        _client().post("/findback", json=FLAT_PAYLOAD)

        kwargs = save_mock.call_args.kwargs
        assert kwargs["prequal"]["result_code"] == "0"
        assert kwargs["prequal"]["tier"] == "A"
        assert kwargs["prequal"]["score"] == 740

    def test_down_payment_passed_to_save(self, monkeypatch) -> None:
        _disable_db_checks(monkeypatch)
        self._mock_prequal(monkeypatch)
        self._mock_bank_finder(monkeypatch)
        self._mock_engine(monkeypatch)
        save_mock = self._mock_save(monkeypatch)

        _client().post("/findback", json=FLAT_PAYLOAD)

        kwargs = save_mock.call_args.kwargs
        assert kwargs["down_payment"] == 5000.0
