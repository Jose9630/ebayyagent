"""Thin wrapper around eBay's Browse API (item_summary/search) with basic
retry/backoff for transient failures (5xx responses, rate limits, network blips).

Docs: https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
"""

from __future__ import annotations

import base64
import logging
import time
from urllib.parse import quote

import requests

from .config import Watch

logger = logging.getLogger("ebay_bot")

_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 1.5


class EbayApiError(RuntimeError):
    """Raised when an eBay API call fails after exhausting retries, or hits a
    non-retryable error."""


class EbayClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._token_expiry: float = 0.0

    def _get_token(self) -> str:
        """Fetch (and cache) an OAuth2 application token via client_credentials grant."""
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        creds = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        resp = self._request_with_retry(
            "POST",
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {creds}",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
        )
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data["expires_in"]
        return self._token

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = requests.request(method, url, timeout=15, **kwargs)
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise EbayApiError(f"Retryable HTTP {resp.status_code} from eBay API")
                resp.raise_for_status()
                return resp
            except (requests.RequestException, EbayApiError) as e:
                last_exc = e
                if attempt < _MAX_RETRIES:
                    wait = _BACKOFF_BASE_SECONDS**attempt
                    logger.warning(
                        f"eBay API call failed (attempt {attempt}/{_MAX_RETRIES}): {e}. "
                        f"Retrying in {wait:.1f}s."
                    )
                    time.sleep(wait)
        raise EbayApiError(f"eBay API request failed after {_MAX_RETRIES} attempts") from last_exc

    def search_watch(
        self,
        watch: Watch,
        limit: int = 50,
        delivery_postal_code: str | None = None,
    ) -> list[dict]:
        """Convenience wrapper: search using the criteria defined on a Watch."""
        return self.search(
            keywords=watch.keywords,
            category_id=watch.category_id or None,
            brands=watch.brands or None,
            min_price=watch.min_price,
            max_price=watch.max_price,
            currency=watch.currency,
            listing_type=watch.listing_type,
            site=watch.site,
            limit=limit,
            delivery_postal_code=delivery_postal_code,
        )

    def search(
        self,
        keywords: str,
        category_id: str | None = None,
        brands: list[str] | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        currency: str = "USD",
        listing_type: str = "BOTH",  # AUCTION | FIXED_PRICE | BOTH
        site: str = "EBAY_US",
        limit: int = 50,
        delivery_postal_code: str | None = None,
    ) -> list[dict]:
        token = self._get_token()

        filters = []
        if min_price is not None or max_price is not None:
            lo = "" if min_price is None else min_price
            hi = "" if max_price is None else max_price
            filters.append(f"price:[{lo}..{hi}]")
            filters.append(f"priceCurrency:{currency}")
        if listing_type == "AUCTION":
            filters.append("buyingOptions:{AUCTION}")
        elif listing_type == "FIXED_PRICE":
            filters.append("buyingOptions:{FIXED_PRICE}")
        filters.append("itemLocationCountry:US")

        # Build the q (keyword) string. eBay's q syntax: space-separated terms are
        # ANDed; a comma-separated group in parentheses is ORed. So keywords="mini pc"
        # with brands=["Beelink","GMKtec"] becomes "mini pc (Beelink,GMKtec)" - must
        # match "mini pc" AND at least one brand. This matches against the actual
        # title/description text, so it catches brand names sellers typed manually,
        # not just ones selected from eBay's structured Brand dropdown (which is all
        # aspect_filter-based Brand matching can see).
        query_parts = []
        if keywords.strip():
            query_parts.append(keywords.strip())
        if brands:
            query_parts.append(f"({','.join(brands)})")
        q = " ".join(query_parts)

        params: dict = {
            "limit": limit,
            "sort": "newlyListed",
            "fields": "itemId,title,price,buyingOptions,itemWebUrl,shippingOptions",
        }
        if q:
            params["q"] = q
        if category_id:
            params["category_ids"] = category_id
        if filters:
            params["filter"] = ",".join(filters)

        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": site,
        }
        contextual_location = "country=US"
        if delivery_postal_code:
            contextual_location += f",zip={delivery_postal_code}"
        headers["X-EBAY-C-ENDUSERCTX"] = f"contextualLocation={quote(contextual_location, safe='')}"

        resp = self._request_with_retry(
            "GET",
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers=headers,
            params=params,
        )
        items = resp.json().get("itemSummaries", [])
        return [item for item in items if (item.get("itemLocation") or {}).get("country") == "US"]
