"""
Credit-pull safeguards on /findback: consent, dealer attribution, customer session,
per-applicant limit — plus approved-only lender matching and /update validation.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.api.routers import findback as findback_module
from app.models.prequal_result import PrequalResult

PAYLOAD = {
    "first_name": "Jane", "last_name": "Doe", "email": "jane@example.com",
    "address": "1 Main St", "city": "SF", "state": "CA", "zip_code": "94102",
    "consent": True,
}


async def _noop() -> None:
    return None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "create_tables", _noop)
    monkeypatch.setattr(main, "test_connection", _noop)

    class FakeCredit:
        calls = 0
        score = 712

        def __init__(self, **_):
            pass

        def send_prequalify(self, **_):
            FakeCredit.calls += 1
            return PrequalResult(raw_xml="<x/>", result_code="0", score=FakeCredit.score)

    monkeypatch.setattr(findback_module, "SevenHundredCreditClient", FakeCredit)
    save = AsyncMock(return_value=7)
    monkeypatch.setattr(findback_module, "save_findback_result", save)
    monkeypatch.setattr(findback_module, "get_engine", lambda: _engine_ctx())
    c = TestClient(main.app)
    c.credit, c.save = FakeCredit, save
    return c


class _Conn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _engine_ctx():
    eng = MagicMock()
    eng.begin = lambda: _Conn()
    return eng


def test_pull_without_consent_is_refused(client):
    resp = client.post("/findback", json={**PAYLOAD, "consent": False})
    assert resp.status_code == 400
    assert client.credit.calls == 0


def test_consent_time_and_ip_are_recorded(client):
    client.post("/findback", json=PAYLOAD, headers={"X-Real-IP": "203.0.113.9"})
    kwargs = client.save.call_args.kwargs
    assert kwargs["consent_at"] is not None
    assert kwargs["client_ip"] == "203.0.113.9"


def test_customer_cannot_attribute_pull_to_a_dealer(client):
    client.post("/findback", json={**PAYLOAD, "dealer_id": "DLR-000001"})
    assert client.save.call_args.kwargs["dealer_id"] is None


def test_dealer_hub_pull_records_dealer(client):
    client.post("/findback", json={**PAYLOAD, "dealer_id": "DLR-000001"}, headers={"X-Service-Token": "test-service-token"})
    assert client.save.call_args.kwargs["dealer_id"] == "DLR-000001"


@pytest.mark.anonymous_customer
def test_anonymous_pull_requires_session(client):
    resp = client.post("/findback", json=PAYLOAD)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "sign in required"
    assert client.credit.calls == 0


def test_pull_uses_session_email_not_payload(client):
    client.post("/findback", json={**PAYLOAD, "email": "someone-else@example.com"})
    kwargs = client.save.call_args.kwargs
    assert kwargs["email"] == "jane@example.com"
    assert kwargs["customer_email"] == "jane@example.com"


def test_customer_response_has_offer_not_credit_result(client):
    body = client.post("/findback", json=PAYLOAD).json()
    assert body["application_id"] == 7
    assert not {"prequal", "upload_token"} & set(body)


@pytest.mark.anonymous_customer
def test_service_token_pull_unchanged(client):
    resp = client.post("/findback", json=PAYLOAD, headers={"X-Service-Token": "test-service-token"})
    assert resp.status_code == 200
    assert "prequal" in resp.json()
    assert client.save.call_args.kwargs["customer_email"] is None


@pytest.mark.real_applicant_limit
@pytest.mark.parametrize("recent,expected", [(2, 200), (3, 429)])
def test_per_account_daily_limit(client, monkeypatch, recent, expected):
    # first COUNT = per-applicant limit, second = per-account limit
    conn = MagicMock(scalar=AsyncMock(side_effect=[0, recent]))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    eng = _engine_ctx()
    eng.connect = lambda: ctx
    monkeypatch.setattr(findback_module, "get_engine", lambda: eng)

    resp = client.post("/findback", json=PAYLOAD)
    assert resp.status_code == expected
    if expected == 429:
        assert resp.json()["detail"] == "you've reached today's limit of credit checks"


@pytest.mark.real_applicant_limit
@pytest.mark.parametrize("recent,expected", [(2, 200), (3, 429)])
def test_per_applicant_daily_limit(client, monkeypatch, recent, expected):
    conn = MagicMock(scalar=AsyncMock(return_value=recent))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    eng = _engine_ctx()
    eng.connect = lambda: ctx
    monkeypatch.setattr(findback_module, "get_engine", lambda: eng)

    assert client.post("/findback", json=PAYLOAD).status_code == expected
    assert client.credit.calls == (1 if expected == 200 else 0)


@pytest.mark.anonymous_customer
@pytest.mark.real_applicant_limit
@pytest.mark.parametrize("recent,expected", [(199, 200), (200, 429)])
def test_per_dealer_daily_limit(client, monkeypatch, recent, expected):
    # first COUNT = per-applicant limit, second = per-dealer limit
    conn = MagicMock(scalar=AsyncMock(side_effect=[0, recent]))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    eng = _engine_ctx()
    eng.connect = lambda: ctx
    monkeypatch.setattr(findback_module, "get_engine", lambda: eng)

    resp = client.post("/findback", json={**PAYLOAD, "dealer_id": "DLR-000001"}, headers={"X-Service-Token": "test-service-token"})
    assert resp.status_code == expected


@pytest.mark.real_applicant_limit
def test_limit_check_fails_closed_without_db(client, monkeypatch):
    def broken():
        raise OSError("db down")

    eng = _engine_ctx()
    eng.connect = broken
    monkeypatch.setattr(findback_module, "get_engine", lambda: eng)
    assert client.post("/findback", json=PAYLOAD).status_code == 503
    assert client.credit.calls == 0


def test_update_rejects_payload_that_is_not_a_rate_sheet(client):
    from app.core.dependencies import get_conn

    async def fake_conn():
        yield MagicMock()

    main.app.dependency_overrides[get_conn] = fake_conn
    try:
        resp = client.post(
            "/update",
            json={"loan_programs": "not-a-list"},
            headers={"X-Service-Token": "test-service-token"},
        )
    finally:
        main.app.dependency_overrides.clear()
    assert resp.status_code == 422


def test_bank_finder_only_matches_approved_lenders():
    import inspect

    from app.services import bank_finder

    assert "approval_status = 'approved'" in inspect.getsource(bank_finder)


# --- Dealer bank network: a dealer's pull is matched only against banks they work with ---

PRICED = {**PAYLOAD, "answers": {"vehicle-price": "30000"}, "otherDownPayment": "5000"}
DEALER_HEADERS = {"X-Service-Token": "test-service-token"}


@pytest.fixture
def bank_finder(monkeypatch):
    finder = AsyncMock(return_value=None)
    network = AsyncMock(return_value=[3, 5])
    monkeypatch.setattr(findback_module, "find_best_bank", finder)
    monkeypatch.setattr(findback_module, "get_dealer_bank_ids", network)
    return finder, network


def test_dealer_pull_searches_only_dealer_network(client, bank_finder):
    finder, network = bank_finder
    client.post("/findback", json={**PRICED, "dealer_id": "DLR-000001"}, headers=DEALER_HEADERS)
    network.assert_awaited_once_with("DLR-000001")
    assert finder.call_args.kwargs["bank_ids"] == [3, 5]


def test_non_dealer_pull_searches_all_banks(client, bank_finder):
    finder, network = bank_finder
    client.post("/findback", json=PRICED, headers=DEALER_HEADERS)
    network.assert_not_awaited()
    assert finder.call_args.kwargs["bank_ids"] is None


def test_dealer_network_unavailable_skips_offer(client, bank_finder, monkeypatch):
    from app.integrations.dealer_hub import DealerHubUnavailableError

    finder, network = bank_finder
    network.side_effect = DealerHubUnavailableError("down")
    resp = client.post("/findback", json={**PRICED, "dealer_id": "DLR-000001"}, headers=DEALER_HEADERS)
    assert resp.status_code == 200
    assert "best_bank" not in resp.json()
    finder.assert_not_awaited()
    assert client.save.call_args.kwargs["best_bank"] is None


@pytest.mark.parametrize("bank_ids, searched", [(None, [1, 2, 3]), ([2], [2]), ([], [])])
def test_bank_finder_restricts_to_given_bank_ids(monkeypatch, bank_ids, searched):
    import asyncio

    from app.services import bank_finder

    async def _county(*_):
        return None

    async def _eligible(*_):
        return [{"bank_id": i, "name": f"B{i}"} for i in (1, 2, 3)]

    rate = AsyncMock(return_value={"bank_name": "B", "interest_rate": "5%", "program_name": "P", "tier_name": "T"})
    monkeypatch.setattr(bank_finder, "_get_county_from_zipcode", _county)
    monkeypatch.setattr(bank_finder, "_get_eligible_banks", _eligible)
    monkeypatch.setattr(bank_finder, "_find_best_rate", rate)

    result = asyncio.run(bank_finder.find_best_bank(None, "94102", 25000.0, 740, bank_ids=bank_ids))

    if searched:
        assert [b["bank_id"] for b in rate.call_args.args[1]] == searched
    else:
        rate.assert_not_awaited()
        assert result is None


def test_dealer_hub_client_sends_service_token(monkeypatch):
    import asyncio

    import httpx

    from app.core.config import get_settings
    from app.integrations import dealer_hub

    seen = {}

    def handler(request):
        seen["url"], seen["token"] = str(request.url), request.headers.get("x-service-token")
        return httpx.Response(200, json={"dealer_id": "DLR-000001", "bank_ids": [3, 5]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(dealer_hub.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(get_settings(), "dealer_hub_base_url", "http://hub:8001/")

    assert asyncio.run(dealer_hub.get_dealer_bank_ids("DLR-000001")) == [3, 5]
    assert seen == {"url": "http://hub:8001/internal/dealers/DLR-000001/bank-ids", "token": "test-service-token"}


# --- Real credit score, save retry, applicant lock ---

def test_bank_match_uses_700credit_score(client, bank_finder):
    finder, _ = bank_finder
    client.post("/findback", json=PRICED, headers=DEALER_HEADERS)
    assert finder.call_args.kwargs["credit_score"] == 712
    assert client.save.call_args.kwargs["credit_score"] == 712


def test_no_score_means_no_bank_match(client, bank_finder, monkeypatch):
    finder, _ = bank_finder
    monkeypatch.setattr(client.credit, "score", None)
    resp = client.post("/findback", json=PRICED, headers=DEALER_HEADERS)
    assert resp.status_code == 200
    finder.assert_not_awaited()
    assert client.save.call_args.kwargs["credit_score"] is None


def test_save_is_retried_once(client):
    client.save.side_effect = [RuntimeError("db blip"), 11]
    resp = client.post("/findback", json=PAYLOAD, headers=DEALER_HEADERS)
    assert resp.json()["application_id"] == 11
    assert client.save.await_count == 2


def test_lost_save_is_logged_for_reconciliation(client, caplog):
    client.save.side_effect = RuntimeError("db down")
    resp = client.post("/findback", json=PAYLOAD, headers=DEALER_HEADERS)
    assert resp.status_code == 200 and "application_id" not in resp.json()
    assert "UNRECORDED CREDIT PULL" in caplog.text
    assert "jane@example.com" not in caplog.text


def test_dealer_pulls_take_the_applicant_lock(client, monkeypatch):
    from contextlib import asynccontextmanager

    taken = []

    @asynccontextmanager
    async def _record(keys):
        taken.append(keys)
        yield

    monkeypatch.setattr(findback_module, "one_pull_at_a_time", _record)
    client.post("/findback", json={**PAYLOAD, "dealer_id": "DLR-000001"}, headers=DEALER_HEADERS)
    assert taken == [["credit-pull-applicant:jane|doe|94102"]]


# --- Security review fixes ---

OFFER = {"bank_id": 3, "bank_name": "B", "interest_rate": "5%", "program_name": "P", "tier_name": "Tier 1 (740+)",
         "term_in_months": 60, "min_loan_amount": 1, "max_loan_amount": 9, "min_credit_score": 740, "max_credit_score": 850}


def test_customer_offer_hides_score_band(client, bank_finder):
    finder, _ = bank_finder
    finder.return_value = dict(OFFER)
    offer = client.post("/findback", json=PRICED).json()["best_bank"]
    assert {"min_credit_score", "max_credit_score", "tier_name"}.isdisjoint(offer)
    assert offer["interest_rate"] == "5%"
    assert client.save.call_args.kwargs["best_bank"]["tier_name"] == "Tier 1 (740+)"  # still stored


def test_dealer_offer_keeps_score_band(client, bank_finder):
    finder, _ = bank_finder
    finder.return_value = dict(OFFER)
    offer = client.post("/findback", json=PRICED, headers=DEALER_HEADERS).json()["best_bank"]
    assert offer["min_credit_score"] == 740


def test_dealer_hub_client_encodes_dealer_id(monkeypatch):
    import asyncio

    import httpx

    from app.core.config import get_settings
    from app.integrations import dealer_hub

    seen = {}

    def handler(request):
        seen["path"] = request.url.raw_path.decode()
        return httpx.Response(200, json={"bank_ids": []})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(dealer_hub.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(get_settings(), "dealer_hub_base_url", "http://hub:8001")
    asyncio.run(dealer_hub.get_dealer_bank_ids("../credit-unions"))
    assert seen["path"] == "/internal/dealers/..%2Fcredit-unions/bank-ids"


def test_engine_hides_sql_parameters_from_errors(monkeypatch):
    import app.db as db

    monkeypatch.setattr(db, "_engine", None)
    assert db.get_engine().sync_engine.hide_parameters is True
    monkeypatch.setattr(db, "_engine", None)
