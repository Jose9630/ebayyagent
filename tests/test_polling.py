"""Verifies the polling/dedup/notification logic using fake eBay data and
mocked Telegram calls - no real network access required."""

from unittest.mock import patch

import pytest

from ebay_bot.commands import BotState, handle_update
from ebay_bot.config import AppConfig, Watch
from ebay_bot.main import poll_ebay_once
from ebay_bot.storage import SeenStore

PASS_1_ITEMS = [
    {
        "itemId": "v1|100001|0",
        "title": "Beelink Mini PC Ryzen 7 16GB RAM 512GB SSD",
        "price": {"value": "219.99", "currency": "USD"},
        "buyingOptions": ["FIXED_PRICE"],
        "itemWebUrl": "https://www.ebay.com/itm/100001",
    },
    {
        "itemId": "v1|100002|0",
        "title": "Intel NUC 11 Mini PC i5",
        "price": {"value": "180.00", "currency": "USD"},
        "buyingOptions": ["AUCTION"],
        "itemWebUrl": "https://www.ebay.com/itm/100002",
    },
]

NEW_ITEM = {
    "itemId": "v1|100003|0",
    "title": "HP EliteDesk Mini PC i7 32GB RAM",
    "price": {"value": "275.50", "currency": "USD"},
    "buyingOptions": ["FIXED_PRICE"],
    "itemWebUrl": "https://www.ebay.com/itm/100003",
}


class FakeEbayClient:
    """Returns a scripted sequence of responses, one per call to search_watch."""

    def __init__(self, responses):
        self._responses = responses
        self.calls = 0

    def search_watch(self, watch):
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


@pytest.fixture
def state(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("poll_interval_seconds: 60\nwatches: []\n")
    config = AppConfig(
        poll_interval_seconds=60,
        watches=[Watch(name="Mini PC deals (test)", keywords="mini pc")],
        path=config_path,
    )
    return BotState(config=config)


@pytest.fixture
def store(tmp_path):
    s = SeenStore(path=str(tmp_path / "seen.db"))
    yield s
    s.close()


def test_baseline_pass_sends_no_notifications(state, store):
    client = FakeEbayClient([PASS_1_ITEMS])
    with patch("ebay_bot.main.notify_telegram") as mock_notify:
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=True)
    mock_notify.assert_not_called()


def test_new_listing_triggers_exactly_one_notification(state, store):
    client = FakeEbayClient([PASS_1_ITEMS, PASS_1_ITEMS + [NEW_ITEM]])
    with patch("ebay_bot.main.notify_telegram") as mock_notify:
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=True)
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=False)

    mock_notify.assert_called_once()
    called_item = mock_notify.call_args[0][2]
    assert called_item["itemId"] == "v1|100003|0"


def test_added_watch_catches_up_silently_then_notifies_new_listings(state, store):
    state.config.watches.clear()
    with patch("ebay_bot.commands.send_message"):
        handle_update(
            {
                "message": {
                    "chat": {"id": 123},
                    "text": "/addwatch New watch | mini pc | 50 | 300 | BOTH",
                }
            },
            state,
            "tok",
            "123",
        )

    client = FakeEbayClient([PASS_1_ITEMS, PASS_1_ITEMS + [NEW_ITEM]])
    with patch("ebay_bot.main.notify_telegram") as mock_notify:
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=False)
        mock_notify.assert_not_called()
        assert not state.pending_baseline_watch_names

        poll_ebay_once(client, store, state, "tok", "chat", first_pass=False)

    mock_notify.assert_called_once()
    assert mock_notify.call_args[0][2]["itemId"] == NEW_ITEM["itemId"]


def test_added_watch_retries_silent_baseline_after_api_error(state, store):
    state.config.watches.clear()
    with patch("ebay_bot.commands.send_message"):
        handle_update(
            {
                "message": {
                    "chat": {"id": 123},
                    "text": "/addwatch New watch | mini pc | 50 | 300 | BOTH",
                }
            },
            state,
            "tok",
            "123",
        )

    class FailingOnceClient:
        calls = 0

        def search_watch(self, watch):
            self.calls += 1
            if self.calls == 1:
                from ebay_bot.ebay_client import EbayApiError

                raise EbayApiError("simulated failure")
            return PASS_1_ITEMS

    client = FailingOnceClient()
    with patch("ebay_bot.main.notify_telegram") as mock_notify:
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=False)
        assert state.pending_baseline_watch_names == {"New watch"}

        poll_ebay_once(client, store, state, "tok", "chat", first_pass=False)

    mock_notify.assert_not_called()
    assert not state.pending_baseline_watch_names


def test_repeat_poll_with_nothing_new_sends_no_notifications(state, store):
    client = FakeEbayClient([PASS_1_ITEMS, PASS_1_ITEMS])
    with patch("ebay_bot.main.notify_telegram") as mock_notify:
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=True)
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=False)
    mock_notify.assert_not_called()


def test_price_drop_updates_stored_price_and_notifies(state, store):
    cheaper_item = {
        **PASS_1_ITEMS[0],
        "price": {"value": "199.99", "currency": "USD"},
    }
    client = FakeEbayClient([[PASS_1_ITEMS[0]], [cheaper_item], [cheaper_item]])
    with patch("ebay_bot.main.notify_telegram") as mock_notify:
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=True)
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=False)
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=False)

    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["price_drop"] is True
    assert mock_notify.call_args.args[2]["price"]["value"] == "199.99"
    assert store.get_last_price(state.watches[0].name, PASS_1_ITEMS[0]["itemId"]) == (
        "199.99",
        "USD",
    )


def test_price_increase_updates_baseline_without_notifying(state, store):
    higher_item = {
        **PASS_1_ITEMS[0],
        "price": {"value": "229.99", "currency": "USD"},
    }
    client = FakeEbayClient([[PASS_1_ITEMS[0]], [higher_item]])
    with patch("ebay_bot.main.notify_telegram") as mock_notify:
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=True)
        poll_ebay_once(client, store, state, "tok", "chat", first_pass=False)

    mock_notify.assert_not_called()
    assert store.get_last_price(state.watches[0].name, PASS_1_ITEMS[0]["itemId"]) == (
        "229.99",
        "USD",
    )


def test_seen_store_migrates_legacy_database(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.execute("""CREATE TABLE seen (
               watch_name TEXT, item_id TEXT, first_seen INTEGER,
               PRIMARY KEY (watch_name, item_id)
           )""")
    connection.execute(
        "INSERT INTO seen (watch_name, item_id, first_seen) VALUES (?, ?, ?)",
        ("watch", "item", 1),
    )
    connection.commit()
    connection.close()

    migrated_store = SeenStore(path=str(db_path))
    try:
        assert migrated_store.get_last_price("watch", "item") == (None, None)
        migrated_store.update_last_price("watch", "item", "12.34", "USD")
        assert migrated_store.get_last_price("watch", "item") == ("12.34", "USD")
    finally:
        migrated_store.close()


def test_ebay_api_error_for_one_watch_does_not_block_others(tmp_path, store):
    from ebay_bot.ebay_client import EbayApiError

    config_path = tmp_path / "config.yaml"
    config_path.write_text("poll_interval_seconds: 60\nwatches: []\n")
    config = AppConfig(
        poll_interval_seconds=60,
        watches=[
            Watch(name="Broken watch", keywords="x"),
            Watch(name="Working watch", keywords="mini pc"),
        ],
        path=config_path,
    )
    state = BotState(config=config)

    class FlakyClient:
        def search_watch(self, watch):
            if watch.name == "Broken watch":
                raise EbayApiError("simulated failure")
            return [NEW_ITEM]

    with patch("ebay_bot.main.notify_telegram") as mock_notify:
        poll_ebay_once(FlakyClient(), store, state, "tok", "chat", first_pass=False)

    # the broken watch's failure shouldn't stop the working watch from notifying
    mock_notify.assert_called_once()
