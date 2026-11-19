"""
Unit tests for app.integrations.dealer_hub_client — the HTTP client
/findback uses to look up a dealer's mapped bank network from
dealer-hub-backend. No real network calls: httpx.MockTransport stands in
for dealer-hub-backend's /internal/dealers/{dealer_id}/bank-ids endpoint.
"""
import httpx
import pytest

from app.core.config import Settings
from app.integrations import dealer_hub_client as client_module
from app.integrations.dealer_hub_client import DealerHubUnavailableError, get_dealer_bank_ids


def _mock_settings(monkeypatch, base_url="http://dealerhub.test") -> None:
    settings = Settings(dealer_hub_base_url=base_url)
    monkeypatch.setattr(client_module, "get_settings", lambda: settings)


def _mock_transport(monkeypatch, handler) -> None:
    """Routes every httpx.AsyncClient() constructed inside the module under
    test through a fake transport instead of the real network."""
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


class TestGetDealerBankIds:
    async def test_returns_bank_ids_from_response(self, monkeypatch) -> None:
        _mock_settings(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/internal/dealers/D-001/bank-ids"
            return httpx.Response(200, json={"dealer_id": "D-001", "bank_ids": [1, 4, 7]})

        _mock_transport(monkeypatch, handler)

        result = await get_dealer_bank_ids("D-001")

        assert result == [1, 4, 7]

    async def test_unknown_dealer_returns_empty_list(self, monkeypatch) -> None:
        _mock_settings(monkeypatch)
        _mock_transport(
            monkeypatch,
            lambda request: httpx.Response(200, json={"dealer_id": "D-999", "bank_ids": []}),
        )

        result = await get_dealer_bank_ids("D-999")

        assert result == []

    async def test_raises_dealer_hub_unavailable_on_http_error(self, monkeypatch) -> None:
        _mock_settings(monkeypatch)
        _mock_transport(monkeypatch, lambda request: httpx.Response(500))

        with pytest.raises(DealerHubUnavailableError):
            await get_dealer_bank_ids("D-001")

    async def test_raises_dealer_hub_unavailable_on_connection_error(self, monkeypatch) -> None:
        _mock_settings(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        _mock_transport(monkeypatch, handler)

        with pytest.raises(DealerHubUnavailableError):
            await get_dealer_bank_ids("D-001")
