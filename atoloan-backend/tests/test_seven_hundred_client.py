"""
Demo unit tests for SevenHundredCreditClient construction.

These only check that the client object is created correctly (attributes,
gateway selection, from_env() wiring) — no network calls, no live gateway.
For the live end-to-end call see test_findback.py::test_findback_integration.
"""
import os
from pathlib import Path

import pytest

from app.integrations.seven_hundred import SevenHundredCreditClient

# Load .env so real SEVENCREDIT_* values are available when this file is run
# on its own (e.g. `pytest tests/test_seven_hundred_client.py`), matching the
# pattern in tests/integration/conftest.py.
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if _ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE, override=False)


class TestSevenHundredCreditClientCreation:
    def test_stores_account_and_password(self) -> None:
        client = SevenHundredCreditClient(account="ACC123", password="PASS123")
        assert client.account == "ACC123"
        assert client.password == "PASS123"

    def test_defaults_to_test_gateway(self) -> None:
        client = SevenHundredCreditClient(account="ACC123", password="PASS123")
        assert client.base_url == SevenHundredCreditClient.TEST_GATEWAY
        assert client.request_url == f"{SevenHundredCreditClient.TEST_GATEWAY}/Request"

    def test_prod_environment_uses_prod_gateway(self) -> None:
        client = SevenHundredCreditClient(account="ACC123", password="PASS123", environment="prod")
        assert client.base_url == SevenHundredCreditClient.PROD_GATEWAY
        assert client.request_url == f"{SevenHundredCreditClient.PROD_GATEWAY}/Request"

    def test_client_id_and_secret_default_to_none(self) -> None:
        client = SevenHundredCreditClient(account="ACC123", password="PASS123")
        assert client.client_id is None
        assert client.client_secret is None

    def test_client_id_and_secret_stored_when_provided(self) -> None:
        client = SevenHundredCreditClient(
            account="ACC123", password="PASS123", client_id="CID", client_secret="CSECRET"
        )
        assert client.client_id == "CID"
        assert client.client_secret == "CSECRET"

    def test_default_timeout_is_15_seconds(self) -> None:
        client = SevenHundredCreditClient(account="ACC123", password="PASS123")
        assert client.timeout == 15

    def test_custom_timeout_is_respected(self) -> None:
        client = SevenHundredCreditClient(account="ACC123", password="PASS123", timeout=30)
        assert client.timeout == 30

    def test_no_access_token_until_first_use(self) -> None:
        client = SevenHundredCreditClient(account="ACC123", password="PASS123")
        assert client._access_token is None
        assert client._token_expiry is None


class TestSevenHundredCreditClientFromEnv:
    def test_from_env_reads_all_variables(self, monkeypatch) -> None:
        monkeypatch.setenv("SEVENCREDIT_ACCOUNT", "ENV_ACC")
        monkeypatch.setenv("SEVENCREDIT_PASSWORD", "ENV_PASS")
        monkeypatch.setenv("SEVENCREDIT_ENV", "prod")
        monkeypatch.setenv("SEVENCREDIT_CLIENT_ID", "ENV_CID")
        monkeypatch.setenv("SEVENCREDIT_CLIENT_SECRET", "ENV_CSECRET")

        client = SevenHundredCreditClient.from_env()

        assert client.account == "ENV_ACC"
        assert client.password == "ENV_PASS"
        assert client.base_url == SevenHundredCreditClient.PROD_GATEWAY
        assert client.client_id == "ENV_CID"
        assert client.client_secret == "ENV_CSECRET"

    def test_from_env_defaults_to_test_when_env_unset(self, monkeypatch) -> None:
        monkeypatch.setenv("SEVENCREDIT_ACCOUNT", "ENV_ACC")
        monkeypatch.setenv("SEVENCREDIT_PASSWORD", "ENV_PASS")
        monkeypatch.delenv("SEVENCREDIT_ENV", raising=False)

        client = SevenHundredCreditClient.from_env()

        assert client.base_url == SevenHundredCreditClient.TEST_GATEWAY

    def test_from_env_raises_when_account_missing(self, monkeypatch) -> None:
        monkeypatch.delenv("SEVENCREDIT_ACCOUNT", raising=False)
        monkeypatch.setenv("SEVENCREDIT_PASSWORD", "ENV_PASS")

        with pytest.raises(ValueError, match="SEVENCREDIT_ACCOUNT and SEVENCREDIT_PASSWORD are required"):
            SevenHundredCreditClient.from_env()

    def test_from_env_raises_when_password_missing(self, monkeypatch) -> None:
        monkeypatch.setenv("SEVENCREDIT_ACCOUNT", "ENV_ACC")
        monkeypatch.delenv("SEVENCREDIT_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="SEVENCREDIT_ACCOUNT and SEVENCREDIT_PASSWORD are required"):
            SevenHundredCreditClient.from_env()


@pytest.mark.skipif(
    not os.getenv("SEVENCREDIT_ACCOUNT") or not os.getenv("SEVENCREDIT_PASSWORD"),
    reason="Missing 700Credit credentials in .env",
)
class TestSevenHundredCreditClientWithRealCredentials:
    """
    Creates the client from the real .env credentials — object construction
    only, no network call to 700Credit. Confirms the credentials configured
    locally actually load into a usable client instance.
    """

    def test_client_created_from_real_env(self) -> None:
        client = SevenHundredCreditClient.from_env()

        assert isinstance(client, SevenHundredCreditClient)
        assert client.account  # non-empty, value not asserted (it's a real secret)
        assert client.password
        assert client.base_url in (
            SevenHundredCreditClient.TEST_GATEWAY,
            SevenHundredCreditClient.PROD_GATEWAY,
        )
        assert client.request_url == f"{client.base_url}/Request"

    def test_real_env_matches_configured_environment(self) -> None:
        client = SevenHundredCreditClient.from_env()
        expected_env = os.getenv("SEVENCREDIT_ENV", "test")

        if expected_env == "prod":
            assert client.base_url == SevenHundredCreditClient.PROD_GATEWAY
        else:
            assert client.base_url == SevenHundredCreditClient.TEST_GATEWAY


@pytest.mark.skipif(
    not os.getenv("SEVENCREDIT_CLIENT_ID") or not os.getenv("SEVENCREDIT_CLIENT_SECRET"),
    reason="Missing 700Credit CLIENT_ID/CLIENT_SECRET in .env",
)
class TestSevenHundredCreditClientBearerToken:
    """
    LIVE test — actually calls POST {base_url}/.auth/token with the real
    SEVENCREDIT_CLIENT_ID/CLIENT_SECRET to obtain a Bearer access token.

    This account requires the resulting token as an Authorization: Bearer
    header on send_prequalify() as well as on sign_iframe_url() — the
    manual only documents ACCOUNT/PASSWD for /Request, but empirically this
    account's PREQUALIFY product also requires the bearer token to
    authenticate (confirmed by test_findback_integration passing once
    send_prequalify started sending it).
    """

    def test_get_access_token_returns_bearer_token(self) -> None:
        client = SevenHundredCreditClient.from_env()

        token = client._get_access_token()

        print(f"\n700Credit bearer token acquired: {token[:20]}...{token[-10:]}")
        print(f"Token expiry: {client._token_expiry}")
        assert token
        assert client._token_expiry is not None

    def test_access_token_is_cached_until_near_expiry(self) -> None:
        client = SevenHundredCreditClient.from_env()

        first_token = client._get_access_token()
        second_token = client._get_access_token()

        assert first_token == second_token  # second call should reuse the cached token
