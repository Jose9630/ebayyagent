"""Safe summaries for Telegram Bot API request errors."""

from __future__ import annotations

import requests


def describe_telegram_error(error: requests.RequestException) -> str:
    response = getattr(error, "response", None)
    if response is None:
        return "network request failed"

    summary = f"HTTP {response.status_code}"
    try:
        description = response.json().get("description")
    except (AttributeError, ValueError):
        description = None
    if description:
        summary = f"{summary}: {description}"
    return summary
