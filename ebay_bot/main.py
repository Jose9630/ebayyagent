"""Main polling loop: checks Telegram for commands, polls eBay on schedule,
and sends notifications for new listings.

Run via `python -m ebay_bot`, or `ebay-bot` if installed with pip.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import time
from pathlib import Path
from types import FrameType

from dotenv import load_dotenv

from .commands import BotState, get_updates, handle_update, send_message
from .config import AppConfig, Credentials
from .ebay_client import EbayApiError, EbayClient
from .logging_config import setup_logging
from .notifier import notify_telegram
from .security import warn_if_env_permissions_insecure
from .storage import SeenStore

logger = logging.getLogger("ebay_bot")

_shutdown_requested = False


def _handle_shutdown_signal(signum: int, frame: FrameType | None) -> None:
    global _shutdown_requested
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    _shutdown_requested = True


def poll_ebay_once(
    client: EbayClient,
    store: SeenStore,
    state: BotState,
    bot_token: str | None,
    chat_id: str | None,
    first_pass: bool,
) -> None:
    completed_baselines: set[str] = set()
    for watch in state.watches:
        baseline_watch = first_pass or watch.name in state.pending_baseline_watch_names
        try:
            items = client.search_watch(watch)
        except EbayApiError as e:
            logger.error(f"[{watch.name}] search failed: {e}")
            continue

        for item in items:
            item_id = item.get("itemId")
            if not item_id:
                continue
            if store.is_new(watch.name, item_id):
                store.mark_seen(watch.name, item_id)
                if baseline_watch:
                    continue
                logger.info(f"[{watch.name}] New listing: {item.get('title')}")
                notify_telegram(bot_token, chat_id, item, watch.name)
        if watch.name in state.pending_baseline_watch_names:
            completed_baselines.add(watch.name)
    state.pending_baseline_watch_names.difference_update(completed_baselines)


def _load_config() -> AppConfig:
    config_path = Path(os.environ.get("CONFIG_PATH", "config.yaml"))
    if config_path != Path("config.yaml") and not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile("config.yaml", config_path)
    return AppConfig.load(config_path)


def main() -> None:
    load_dotenv()
    setup_logging()
    warn_if_env_permissions_insecure()

    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    try:
        config = _load_config()
        creds = Credentials.from_env()
    except (FileNotFoundError, RuntimeError) as e:
        logger.error(f"Startup failed: {e}")
        raise SystemExit(1) from e

    client = EbayClient(client_id=creds.ebay_client_id, client_secret=creds.ebay_client_secret)
    store = SeenStore(path=creds.seen_db_path)

    if not (creds.telegram_bot_token and creds.telegram_chat_id):
        logger.warning(
            "Telegram not configured (check your .env file) - commands and alerts disabled."
        )

    state = BotState(config=config)

    logger.info(
        f"Starting eBay listing bot: {len(config.watches)} watch(es), "
        f"polling every {config.poll_interval_seconds}s."
    )
    if creds.telegram_bot_token and creds.telegram_chat_id:
        send_message(
            creds.telegram_bot_token,
            creds.telegram_chat_id,
            "🤖 eBay Watcher Bot started. Send /help for commands.",
        )

    first_pass = True
    last_ebay_poll = 0.0
    telegram_offset: int | None = None

    try:
        while not _shutdown_requested:
            if creds.telegram_bot_token and creds.telegram_chat_id:
                updates, telegram_offset = get_updates(
                    creds.telegram_bot_token, telegram_offset, timeout=5
                )
                for update in updates:
                    handle_update(update, state, creds.telegram_bot_token, creds.telegram_chat_id)
            else:
                time.sleep(5)

            now = time.time()
            if not state.paused and now - last_ebay_poll >= state.poll_interval:
                poll_ebay_once(
                    client,
                    store,
                    state,
                    creds.telegram_bot_token,
                    creds.telegram_chat_id,
                    first_pass,
                )
                last_ebay_poll = now
                state.last_poll_time = now
                first_pass = False
    finally:
        store.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
