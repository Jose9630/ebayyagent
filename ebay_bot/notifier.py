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

import requests

logger = logging.getLogger("ebay_bot")


def _format_price(item: dict) -> str:
    price = item.get("price", {})
    return f"{price.get('value', '?')} {price.get('currency', '')}".strip()


def notify_telegram(
    bot_token: str | None, chat_id: str | None, item: dict, watch_name: str
) -> None:
    """Sends a message via the Telegram Bot API. Failures are logged, never raised,
    so a Telegram outage doesn't crash the polling loop."""
    if not (bot_token and chat_id):
        return

    title = item.get("title", "New listing")
    link = item.get("itemWebUrl", "")
    buying_options = ", ".join(item.get("buyingOptions", []))

    text = (
        f"🆕 <b>{html.escape(watch_name)}</b>\n"
        f"{html.escape(title)}\n"
        f"💰 {html.escape(_format_price(item))}  |  {html.escape(buying_options)}\n"
        f'<a href="{html.escape(link)}">View on eBay</a>'
    )

    try:
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
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"[telegram] failed to send notification: {e}")
