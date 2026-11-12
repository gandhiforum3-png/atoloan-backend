"""
Client for dealer-hub-backend's server-to-server endpoints.
"""
import logging
from urllib.parse import quote

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class DealerHubUnavailableError(Exception):
    pass


async def get_dealer_bank_ids(dealer_id: str) -> list[int]:
    """Bank ids in the dealer's network. Empty = the dealer hasn't picked any banks."""
    settings = get_settings()
    url = f"{settings.dealer_hub_base_url.rstrip('/')}/internal/dealers/{quote(dealer_id, safe='')}/bank-ids"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers={"X-Service-Token": settings.service_token})
            response.raise_for_status()
        return [int(i) for i in response.json()["bank_ids"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.exception("dealer-hub bank network lookup failed")
        raise DealerHubUnavailableError(str(exc)) from exc
