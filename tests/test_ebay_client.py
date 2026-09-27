from unittest.mock import MagicMock, patch

import pytest
import requests

from ebay_bot.ebay_client import EbayApiError, EbayClient


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_get_token_is_cached_across_calls():
    client = EbayClient("id", "secret")
    token_response = _mock_response(200, {"access_token": "abc123", "expires_in": 7200})

    with patch(
        "ebay_bot.ebay_client.requests.request", return_value=token_response
    ) as mock_request:
        token1 = client._get_token()
        token2 = client._get_token()

    assert token1 == token2 == "abc123"
    mock_request.assert_called_once()  # second call used the cache, no new request


def test_search_retries_on_5xx_then_succeeds():
    client = EbayClient("id", "secret")
    client._token = "cached-token"
    client._token_expiry = 9_999_999_999  # far future, skip token fetch

    fail_response = _mock_response(503)
    ok_response = _mock_response(
        200,
        {"itemSummaries": [{"itemId": "1", "itemLocation": {"country": "US"}}]},
    )

    with (
        patch("ebay_bot.ebay_client.requests.request", side_effect=[fail_response, ok_response]),
        patch("ebay_bot.ebay_client.time.sleep"),
    ):  # skip real backoff delay in tests
        results = client.search(keywords="mini pc")

    assert results == [{"itemId": "1", "itemLocation": {"country": "US"}}]


def test_search_only_returns_listings_with_us_location():
    client = EbayClient("id", "secret")
    client._token = "cached-token"
    client._token_expiry = 9_999_999_999

    items = [
        {"itemId": "us", "itemLocation": {"country": "US"}},
        {"itemId": "uk", "itemLocation": {"country": "GB"}},
        {"itemId": "null-location", "itemLocation": None},
        {"itemId": "unknown"},
    ]
    response = _mock_response(200, {"itemSummaries": items})

    with patch("ebay_bot.ebay_client.requests.request", return_value=response) as mock_request:
        results = client.search(keywords="mini pc")

    assert results == [items[0]]
    assert "itemLocationCountry:US" in mock_request.call_args.kwargs["params"]["filter"]


def test_search_raises_after_exhausting_retries():
    client = EbayClient("id", "secret")
    client._token = "cached-token"
    client._token_expiry = 9_999_999_999

    fail_response = _mock_response(503)

    with (
        patch("ebay_bot.ebay_client.requests.request", return_value=fail_response),
        patch("ebay_bot.ebay_client.time.sleep"),
    ):
        with pytest.raises(EbayApiError):
            client.search(keywords="mini pc")


def test_search_watch_uses_watch_criteria():
    from ebay_bot.config import Watch

    client = EbayClient("id", "secret")
    client._token = "cached-token"
    client._token_expiry = 9_999_999_999
    watch = Watch(name="MiniPC", keywords="mini pc", min_price=50, max_price=300, category_id="179")

    ok_response = _mock_response(200, {"itemSummaries": []})
    with patch("ebay_bot.ebay_client.requests.request", return_value=ok_response) as mock_request:
        client.search_watch(watch)

    call_kwargs = mock_request.call_args.kwargs
    assert call_kwargs["params"]["q"] == "mini pc"
    assert call_kwargs["params"]["category_ids"] == "179"
    assert "price:[50..300]" in call_kwargs["params"]["filter"]


def test_search_builds_or_group_in_q_for_brands():
    from ebay_bot.config import Watch

    client = EbayClient("id", "secret")
    client._token = "cached-token"
    client._token_expiry = 9_999_999_999
    watch = Watch(
        name="MiniPC brands",
        keywords="",
        category_id="179",
        brands=["Beelink", "GMKtec", "Minisforum"],
    )

    ok_response = _mock_response(200, {"itemSummaries": []})
    with patch("ebay_bot.ebay_client.requests.request", return_value=ok_response) as mock_request:
        client.search_watch(watch)

    assert mock_request.call_args.kwargs["params"]["q"] == "(Beelink,GMKtec,Minisforum)"


def test_search_combines_keywords_and_brands_with_and():
    client = EbayClient("id", "secret")
    client._token = "cached-token"
    client._token_expiry = 9_999_999_999

    ok_response = _mock_response(200, {"itemSummaries": []})
    with patch("ebay_bot.ebay_client.requests.request", return_value=ok_response) as mock_request:
        client.search(keywords="mini pc", brands=["Beelink", "GMKtec"])

    assert mock_request.call_args.kwargs["params"]["q"] == "mini pc (Beelink,GMKtec)"


def test_search_allows_brands_without_category_id():
    # No longer required now that brands feed into q instead of aspect_filter.
    client = EbayClient("id", "secret")
    client._token = "cached-token"
    client._token_expiry = 9_999_999_999

    ok_response = _mock_response(200, {"itemSummaries": []})
    with patch("ebay_bot.ebay_client.requests.request", return_value=ok_response) as mock_request:
        client.search(keywords="", brands=["Beelink"])

    assert mock_request.call_args.kwargs["params"]["q"] == "(Beelink)"
    assert "category_ids" not in mock_request.call_args.kwargs["params"]


def test_search_omits_q_param_when_keywords_empty():
    # Sending q="" to eBay can return zero results rather than "no keyword filter",
    # so an empty keywords string must omit the q param entirely.
    client = EbayClient("id", "secret")
    client._token = "cached-token"
    client._token_expiry = 9_999_999_999

    ok_response = _mock_response(200, {"itemSummaries": []})
    with patch("ebay_bot.ebay_client.requests.request", return_value=ok_response) as mock_request:
        client.search(keywords="", category_id="179")

    assert "q" not in mock_request.call_args.kwargs["params"]
    assert mock_request.call_args.kwargs["params"]["category_ids"] == "179"
