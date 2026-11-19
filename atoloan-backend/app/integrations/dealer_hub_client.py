"""
Client for dealer-hub-backend's dealer -> bank network mapping.

atoloan-backend has no dealer data of its own — dealer-hub-backend owns the
bank_dealer table, so we go through its unauthenticated /internal API
rather than reading its database directly. Mirrors, in reverse, the same
pattern dealer-hub-backend already uses to read *this* service's bank data
via GET {atoloan_backend_base_url}/credit-unions.
"""
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class DealerHubUnavailableError(Exception):
    pass


async def get_dealer_bank_ids(dealer_id: str) -> list[int]:
    """
    Bank ids in this dealer's network. An unknown dealer_id, or a known
    dealer who hasn't selected any banks yet, both just come back as an
    empty list from dealer-hub-backend — not distinguished here.

    Raises DealerHubUnavailableError on any network/HTTP failure — it's up
    to the caller whether that means "search all banks" or "skip bank
    search entirely" for this request.
    """
    settings = get_settings()
    url = f"{settings.dealer_hub_base_url.rstrip('/')}/internal/dealers/{dealer_id}/bank-ids"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("dealer-hub bank lookup failed for dealer_id=%s", dealer_id)
        raise DealerHubUnavailableError(str(exc)) from exc

    return response.json().get("bank_ids", [])
