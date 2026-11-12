import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


TEST_SERVICE_TOKEN = "test-service-token"


@pytest.fixture(autouse=True)
def _service_token(monkeypatch):
    """Known X-Service-Token for the routes that require one."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "service_token", TEST_SERVICE_TOKEN)


@pytest.fixture(autouse=True)
def _no_applicant_limit_db(request, monkeypatch):
    """Unit tests have no Postgres: skip /findback's DB-backed per-applicant
    and per-dealer limits unless a test opts in with @pytest.mark.real_applicant_limit."""
    if request.node.get_closest_marker("real_applicant_limit"):
        return

    async def _noop(_payload):
        return None

    monkeypatch.setattr("app.api.routers.findback._enforce_applicant_limit", _noop)
    monkeypatch.setattr("app.api.routers.findback._enforce_dealer_limit", _noop)
    monkeypatch.setattr("app.api.routers.findback._enforce_account_limit", _noop)


@pytest.fixture(autouse=True)
def _placeholder_700credit_credentials(monkeypatch):
    """Let mocked /findback tests reach their fake 700Credit client.

    The router rejects requests before building the client when credentials
    are blank, so without this the mocked tests only pass on machines whose
    .env holds real credentials. Real credentials, when present, are untouched.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.sevencredit_account:
        monkeypatch.setattr(settings, "sevencredit_account", "test-account")
    if not settings.sevencredit_password:
        monkeypatch.setattr(settings, "sevencredit_password", "test-password")


TEST_CUSTOMER = {
    "email": "jane@example.com", "first_name": "Jane", "last_name": "Doe", "phone_number": None,
    "address": None, "city": None, "state": None, "zipcode": None,
}


@pytest.fixture(autouse=True)
def _signed_in_customer(request):
    """Customer routes need a session: unit tests run as TEST_CUSTOMER unless
    marked @pytest.mark.anonymous_customer (no session at all)."""
    if request.node.get_closest_marker("anonymous_customer"):
        yield
        return
    from app.core.customer_session import optional_customer
    from app.main import app

    app.dependency_overrides[optional_customer] = lambda: dict(TEST_CUSTOMER)
    yield
    app.dependency_overrides.pop(optional_customer, None)


@pytest.fixture(autouse=True)
def _no_pull_lock_db(request, monkeypatch):
    """Unit tests have no Postgres: the per-account pull lock is a no-op unless
    a test opts in with @pytest.mark.real_pull_lock."""
    if request.node.get_closest_marker("real_pull_lock"):
        return
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _no_lock(_email):
        yield

    monkeypatch.setattr("app.api.routers.findback.one_pull_at_a_time", _no_lock)
