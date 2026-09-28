"""Typed configuration: watch criteria (config.yaml) and credentials (.env)."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("ebay_bot")

VALID_LISTING_TYPES = {"AUCTION", "FIXED_PRICE", "BOTH"}


@dataclass
class Watch:
    """A single search filter: what to look for and how to filter results."""

    name: str
    keywords: str
    category_id: str = ""
    brands: list[str] = field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None
    currency: str = "USD"
    listing_type: str = "BOTH"  # AUCTION | FIXED_PRICE | BOTH
    site: str = "EBAY_US"

    def __post_init__(self) -> None:
        self.listing_type = self.listing_type.upper()
        if self.listing_type not in VALID_LISTING_TYPES:
            raise ValueError(
                f"listing_type must be one of {sorted(VALID_LISTING_TYPES)}, "
                f"got {self.listing_type!r}"
            )
        if not self.name.strip():
            raise ValueError("Watch name cannot be empty")
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError(
                f"min_price ({self.min_price}) cannot exceed max_price ({self.max_price}) "
                f"for watch {self.name!r}"
            )
        if not self.keywords.strip() and not self.category_id and not self.brands:
            raise ValueError(
                f"watch {self.name!r} has no keywords, category_id, or brands - eBay's "
                "search requires at least one of them"
            )
        if self.brands and not self.category_id:
            logger.warning(
                f"watch {self.name!r} uses brands without a category_id - matches "
                "will be scoped to all of eBay, not a specific category. Set "
                "category_id unless that's intentional."
            )

    @classmethod
    def from_dict(cls, data: dict) -> Watch:
        return cls(
            name=data["name"],
            keywords=data.get("keywords", ""),
            category_id=data.get("category_id") or "",
            brands=list(data.get("brands") or []),
            min_price=data.get("min_price"),
            max_price=data.get("max_price"),
            currency=data.get("currency", "USD"),
            listing_type=data.get("listing_type", "BOTH"),
            site=data.get("site", "EBAY_US"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AppConfig:
    """Everything loaded from config.yaml. Call save_watches() after mutating
    `watches` in place (e.g. via /addwatch, /removewatch) to persist changes."""

    poll_interval_seconds: int
    watches: list[Watch] = field(default_factory=list)
    path: Path = field(default_factory=lambda: Path("config.yaml"))

    @classmethod
    def load(cls, path: str | Path) -> AppConfig:
        path = Path(path)
        with path.open() as f:
            raw = yaml.safe_load(f) or {}
        watches = [Watch.from_dict(w) for w in raw.get("watches", [])]
        return cls(
            poll_interval_seconds=raw.get("poll_interval_seconds", 40),
            watches=watches,
            path=path,
        )

    def save(self) -> None:
        with self.path.open() as f:
            raw = yaml.safe_load(f) or {}
        raw["poll_interval_seconds"] = self.poll_interval_seconds
        raw["watches"] = [w.to_dict() for w in self.watches]
        with self.path.open("w") as f:
            yaml.safe_dump(raw, f, sort_keys=False)

    def save_watches(self) -> None:
        self.save()


@dataclass
class Credentials:
    """Secrets and connection details loaded from environment variables (.env)."""

    ebay_client_id: str
    ebay_client_secret: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    seen_db_path: str

    @classmethod
    def from_env(cls) -> Credentials:
        missing = [
            var for var in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET") if not os.environ.get(var)
        ]
        if missing:
            raise RuntimeError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set them in your hosting environment or copy .env.example to .env."
            )
        return cls(
            ebay_client_id=os.environ["EBAY_CLIENT_ID"],
            ebay_client_secret=os.environ["EBAY_CLIENT_SECRET"],
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
            seen_db_path=os.environ.get("SEEN_DB_PATH", "seen_items.db"),
        )
