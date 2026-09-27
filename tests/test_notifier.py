"""Regression tests for the '400 Bad Request' Telegram bug: eBay titles or watch
names containing *, _, [, ], &, <, > must never break the outgoing message."""

from unittest.mock import MagicMock, patch

from ebay_bot.notifier import notify_telegram


def test_notify_telegram_uses_html_parse_mode():
    item = {
        "title": "Beelink Mini PC",
        "price": {"value": "199.99", "currency": "USD"},
        "buyingOptions": ["FIXED_PRICE"],
        "itemWebUrl": "https://www.ebay.com/itm/123",
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    with patch("ebay_bot.notifier.requests.post", return_value=mock_resp) as mock_post:
        notify_telegram("tok", "chat", item, "Mini PC deals")

    assert mock_post.call_args.kwargs["data"]["parse_mode"] == "HTML"


def test_notify_telegram_escapes_markdown_breaking_title():
    # This exact shape of title (unmatched * and _, plus & and <>) previously
    # caused Telegram to reject the message with 400 Bad Request under Markdown mode.
    item = {
        "title": '12" HP Desktop *NEW* <Fast_Deal> & More_Stuff [Bundle]',
        "price": {"value": "199.99", "currency": "USD"},
        "buyingOptions": ["FIXED_PRICE"],
        "itemWebUrl": "https://www.ebay.com/itm/123?a=1&b=2",
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    with patch("ebay_bot.notifier.requests.post", return_value=mock_resp) as mock_post:
        notify_telegram("tok", "chat", item, "Mini PC's & Deals")

    text = mock_post.call_args.kwargs["data"]["text"]
    # raw angle brackets/ampersands must not appear unescaped (would break HTML parsing)
    assert "<Fast_Deal>" not in text
    assert "&lt;Fast_Deal&gt;" in text
    assert "&amp;" in text
    # asterisks/underscores/brackets are harmless in HTML mode - no escaping needed,
    # they just render as literal characters
    assert "*NEW*" in text
    assert "[Bundle]" in text
    # watch name (also arbitrary/user-controlled) is escaped too
    assert "Mini PC&#x27;s &amp; Deals" in text


def test_notify_telegram_noop_without_credentials():
    with patch("ebay_bot.notifier.requests.post") as mock_post:
        notify_telegram(None, None, {"title": "x"}, "watch")
    mock_post.assert_not_called()
