"""Sends notifications for a matched listing via a Telegram bot.

Uses HTML parse mode rather than Markdown: eBay listing titles routinely
contain characters like *, _, [, ] that break Telegram's Markdown parser and
cause the whole message to be rejected with a 400 Bad Request. HTML mode only
requires &, <, > to be escaped (handled by Python's html.escape()), which is
far more robust against arbitrary, uncontrolled title text.
"""

from __future__ import annotations

import html
import logging
import time

import requests

from .telegram_errors import describe_telegram_error

logger = logging.getLogger("ebay_bot")


def _format_price(item: dict) -> str:
    price = item.get("price", {})
    return f"{price.get('value', '?')} {price.get('currency', '')}".strip()


def _format_shipping(item: dict) -> str | None:
    candidates: list[dict] = []
    for key in ("shippingOptions", "shippingInfo", "shipping", "shippingCost"):
        value = item.get(key)
        if isinstance(value, list):
            candidates.extend(v for v in value if isinstance(v, dict))
        elif isinstance(value, dict):
            candidates.append(value)

    for candidate in candidates:
        shipping_cost = (
            candidate.get("shippingCost")
            or candidate.get("price")
            or candidate.get("cost")
            or candidate.get("shipping")
        )
        if isinstance(shipping_cost, dict):
            value = shipping_cost.get("value")
            currency = shipping_cost.get("currency")
            if value is not None:
                if str(value).strip() in {"0", "0.0", "0.00"}:
                    return "FREE"
                return f"{value} {currency}".strip() if currency else str(value)

        shipping_cost_type = str(candidate.get("shippingCostType", "")).upper()
        if shipping_cost_type == "FREE":
            return "FREE"

    top_level = item.get("shippingCost")
    if isinstance(top_level, dict):
        value = top_level.get("value")
        currency = top_level.get("currency")
        if value is not None:
            if str(value).strip() in {"0", "0.0", "0.00"}:
                return "FREE"
            return f"{value} {currency}".strip() if currency else str(value)

    return None


def notify_telegram(
    bot_token: str | None,
    chat_id: str | None,
    item: dict,
    watch_name: str,
    price_drop: bool = False,
) -> None:
    """Sends a message via the Telegram Bot API. Failures are logged, never raised,
    so a Telegram outage doesn't crash the polling loop."""
    if not (bot_token and chat_id):
        return

    title = item.get("title", "New listing")
    link = item.get("itemWebUrl", "")
    buying_options = ", ".join(item.get("buyingOptions", []))
    shipping_fee = _format_shipping(item)
    heading = "📉 Price drop" if price_drop else "🆕"

    lines = [
        f"{heading} <b>{html.escape(watch_name)}</b>",
        html.escape(title),
        f"💰 {html.escape(_format_price(item))}  |  {html.escape(buying_options)}",
    ]
    if shipping_fee:
        lines.append(f"Shipping: {html.escape(shipping_fee)}")
    lines.append(f'<a href="{html.escape(link)}">View on eBay</a>')
    text = "\n".join(lines)

    try:
        for attempt in range(3):
            resp = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=10,
            )
            if resp.status_code == 429 and attempt < 2:
                try:
                    retry_after = int(resp.json().get("parameters", {}).get("retry_after", 1))
                except (ValueError, TypeError, AttributeError):
                    retry_after = 1
                time.sleep(max(1, retry_after))
                continue
            resp.raise_for_status()
            break
    except requests.RequestException as e:
        logger.warning("[telegram] failed to send notification: %s", describe_telegram_error(e))
