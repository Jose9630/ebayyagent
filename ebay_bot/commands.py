"""Telegram bot command handling: /status, /cycle, /pause, /resume, /addwatch,
/exkeyword, /removewatch, /listwatches, /help. Only responds to the chat_id configured
in .env, so random people can't control your bot.

Uses Telegram's HTML parse mode (not Markdown) since eBay listing titles and
user-typed watch names/keywords can contain characters like *, _, [, ] that
break Telegram's Markdown parser and cause "400 Bad Request" send failures.
HTML mode only needs &, <, > escaped, which Python's html.escape() handles.
"""

from __future__ import annotations

import html
import logging
import math
import re
import time
from dataclasses import dataclass, field

import requests

from .config import AppConfig, Watch
from .storage import SeenStore
from .telegram_errors import describe_telegram_error

logger = logging.getLogger("ebay_bot")


@dataclass
class BotState:
    config: AppConfig
    paused: bool = False
    cycle_end_time: float | None = None
    last_poll_time: float | None = None
    pending_baseline_watch_names: set[str] = field(default_factory=set)
    start_time: float = field(default_factory=time.time)
    store: SeenStore | None = None
    delivery_postal_code: str | None = None

    @property
    def watches(self) -> list[Watch]:
        return self.config.watches

    @property
    def poll_interval(self) -> int:
        return self.config.poll_interval_seconds

    def pause_if_cycle_expired(self, now: float) -> bool:
        if self.cycle_end_time is None or now < self.cycle_end_time:
            return False
        self.cycle_end_time = None
        self.paused = True
        return True


def get_updates(bot_token: str, offset: int | None = None, timeout: int = 5):
    """Long-polls Telegram for new messages. Returns (updates, new_offset)."""
    params: dict = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            params=params,
            timeout=timeout + 10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("[telegram] failed to fetch updates: %s", describe_telegram_error(e))
        return [], offset

    results = data.get("result", [])
    new_offset = offset
    if results:
        new_offset = results[-1]["update_id"] + 1
    return results, new_offset


def send_message(bot_token: str, chat_id: str, text: str) -> None:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("[telegram] failed to send message: %s", describe_telegram_error(e))


def _format_watch(w: Watch) -> str:
    name = html.escape(w.name)
    keywords = html.escape(w.keywords)
    line = (
        f'• <b>{name}</b> — "{keywords}" '
        f"${w.min_price if w.min_price is not None else 0}-"
        f"${w.max_price if w.max_price is not None else '?'} "
        f"({w.listing_type})"
    )
    if w.category_id:
        line += f" [cat {html.escape(w.category_id)}]"
    if w.brands:
        line += f" [brands: {html.escape(', '.join(w.brands))}]"
    return line


HELP_TEXT = (
    "<b>eBay Watcher Bot</b>\n"
    "/status — show current status\n"
    "/interval [seconds] — show or change the polling interval\n"
    "/cycle hours — run for this many hours, then pause (decimals allowed; "
    "example: <code>/cycle 1.5</code>)\n"
    "/zipcode [US ZIP] — set or view the private shipping ZIP; use 'clear' to remove it\n"
    "/pause — pause polling\n"
    "/resume — resume polling\n"
    "/listwatches — show active watches\n"
    "/addwatch name | keywords | min | max | type | site | category_id | brands\n"
    "  example: <code>/addwatch MiniPCs | mini pc | 50 | 300 | BOTH | EBAY_US | 179 | "
    "Beelink,GMKtec,Minisforum</code>\n"
    "  type is AUCTION, FIXED_PRICE, or BOTH.\n"
    "  site, category_id, brands are optional. brands is a comma-separated list,\n"
    "  OR-matched against listing titles - catches brands sellers typed manually too.\n"
    "/exkeyword watch name | keyword — exclude a title keyword from alerts for that watch\n"
    "/removewatch name — remove a watch by name"
)


def handle_update(update: dict, state: BotState, bot_token: str, allowed_chat_id: str) -> None:
    message = update.get("message")
    if not message:
        return

    chat_id = str(message.get("chat", {}).get("id"))
    text = (message.get("text") or "").strip()

    if str(allowed_chat_id) != chat_id:
        logger.warning(f"Ignoring command from unauthorized chat_id={chat_id}")
        return

    if not text.startswith("/"):
        return

    parts = text.split(" ", 1)
    command = parts[0].lower().split("@")[0]  # strip "@botname" if present
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/start", "/help"):
        send_message(bot_token, chat_id, HELP_TEXT)

    elif command == "/status":
        uptime_min = int((time.time() - state.start_time) / 60)
        last_poll = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(state.last_poll_time))
            if state.last_poll_time
            else "never yet"
        )
        cycle_status = (
            f"active ({math.ceil(max(0, state.cycle_end_time - time.time()) / 60)} min remaining)"
            if state.cycle_end_time is not None
            else "not scheduled"
        )
        send_message(
            bot_token,
            chat_id,
            f"Status: {'⏸ paused' if state.paused else '▶️ running'}\n"
            f"Uptime: {uptime_min} min\n"
            f"Watches: {len(state.watches)}\n"
            f"Poll interval: {state.poll_interval}s\n"
            f"Cycle: {cycle_status}\n"
            f"Last poll: {last_poll}",
        )

    elif command == "/cycle":
        if not arg:
            if state.cycle_end_time is None:
                send_message(bot_token, chat_id, "No timed cycle is active.")
            else:
                remaining_min = math.ceil(max(0, state.cycle_end_time - time.time()) / 60)
                send_message(
                    bot_token,
                    chat_id,
                    f"Timed cycle active: {remaining_min} min remaining.",
                )
            return
        try:
            hours = float(arg)
            duration_seconds = hours * 3600
            if hours <= 0 or not math.isfinite(duration_seconds):
                raise ValueError
        except ValueError:
            send_message(
                bot_token,
                chat_id,
                "Usage: /cycle [positive number of hours, decimals allowed]",
            )
            return

        state.paused = False
        state.cycle_end_time = time.time() + duration_seconds
        send_message(bot_token, chat_id, f"▶️ Cycle started for {hours:g} hour(s).")

    elif command == "/interval":
        if not arg:
            send_message(bot_token, chat_id, f"Polling interval: {state.poll_interval}s")
            return
        try:
            interval = int(arg)
            if interval <= 0:
                raise ValueError
        except ValueError:
            send_message(
                bot_token,
                chat_id,
                "Usage: /interval [positive whole number of seconds]",
            )
            return

        state.config.poll_interval_seconds = interval
        state.config.save()
        send_message(bot_token, chat_id, f"Polling interval set to {interval}s.")

    elif command == "/zipcode":
        if state.store is None:
            send_message(bot_token, chat_id, "Private ZIP storage is unavailable.")
            return
        if not arg:
            status = "set" if state.delivery_postal_code else "not set"
            send_message(bot_token, chat_id, f"Shipping ZIP is {status}.")
            return
        if arg.casefold() == "clear":
            state.store.set_setting("delivery_postal_code", None)
            state.delivery_postal_code = None
            send_message(bot_token, chat_id, "Shipping ZIP cleared.")
            return
        if not re.fullmatch(r"\d{5}(?:-\d{4})?", arg):
            send_message(
                bot_token,
                chat_id,
                "Usage: <code>/zipcode 12345</code> or <code>/zipcode clear</code>",
            )
            return
        state.store.set_setting("delivery_postal_code", arg)
        state.delivery_postal_code = arg
        send_message(bot_token, chat_id, "Shipping ZIP saved privately.")

    elif command == "/pause":
        state.paused = True
        state.cycle_end_time = None
        send_message(bot_token, chat_id, "⏸ Paused. Send /resume to continue.")

    elif command == "/resume":
        state.paused = False
        state.cycle_end_time = None
        send_message(bot_token, chat_id, "▶️ Resumed.")

    elif command == "/listwatches":
        if not state.watches:
            send_message(bot_token, chat_id, "No watches configured.")
        else:
            lines = [_format_watch(w) for w in state.watches]
            send_message(bot_token, chat_id, "<b>Active watches:</b>\n" + "\n".join(lines))

    elif command == "/addwatch":
        try:
            fields = [p.strip() for p in arg.split("|")]
            name, keywords, min_price, max_price, listing_type = fields[:5]
            site = fields[5] if len(fields) > 5 else "EBAY_US"
            category_id = fields[6] if len(fields) > 6 else ""
            brands = (
                [b.strip() for b in fields[7].split(",") if b.strip()]
                if len(fields) > 7 and fields[7]
                else []
            )
            new_watch = Watch(
                name=name,
                keywords=keywords,
                category_id=category_id,
                brands=brands,
                min_price=float(min_price),
                max_price=float(max_price),
                currency="USD",
                listing_type=listing_type.upper(),
                site=site,
            )
            state.config.watches.append(new_watch)
            state.config.save_watches()
            state.pending_baseline_watch_names.add(new_watch.name)
            send_message(bot_token, chat_id, f"Added watch:\n{_format_watch(new_watch)}")
        except Exception as e:
            send_message(
                bot_token,
                chat_id,
                "Couldn't parse that. Format:\n"
                "<code>/addwatch name | keywords | min_price | max_price | "
                "listing_type | site | category_id | brands</code>\n"
                f"Error: {html.escape(str(e))}",
            )

    elif command == "/exkeyword":
        fields = arg.split("|", 1)
        if len(fields) != 2 or not fields[0].strip() or not fields[1].strip():
            send_message(
                bot_token,
                chat_id,
                "Usage: <code>/exkeyword watch name | keyword</code>",
            )
            return

        watch_name, keyword = (field.strip() for field in fields)
        matches = [w for w in state.watches if w.name.casefold() == watch_name.casefold()]
        if not matches:
            send_message(bot_token, chat_id, f"No watch found named: {html.escape(watch_name)}")
            return
        if len(matches) > 1:
            send_message(
                bot_token, chat_id, f"More than one watch is named: {html.escape(watch_name)}"
            )
            return

        watch = matches[0]
        if any(existing.casefold() == keyword.casefold() for existing in watch.exclude_keywords):
            send_message(
                bot_token,
                chat_id,
                f'"{html.escape(keyword)}" is already excluded for {html.escape(watch.name)}.',
            )
            return

        watch.exclude_keywords.append(keyword)
        state.config.save_watches()
        send_message(
            bot_token,
            chat_id,
            f'Added "{html.escape(keyword)}" to excluded keywords for '
            f"{html.escape(watch.name)}.",
        )

    elif command == "/removewatch":
        name = arg.strip()
        before = len(state.watches)
        state.config.watches = [w for w in state.watches if w.name.lower() != name.lower()]
        if len(state.watches) < before:
            state.config.save_watches()
            send_message(bot_token, chat_id, f"Removed watch: {html.escape(name)}")
        else:
            send_message(bot_token, chat_id, f"No watch found named: {html.escape(name)}")

    else:
        send_message(bot_token, chat_id, "Unknown command. Send /help for the list.")
