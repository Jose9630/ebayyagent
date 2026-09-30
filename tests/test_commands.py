import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from ebay_bot.commands import BotState, handle_update, send_message
from ebay_bot.config import AppConfig, Watch

ALLOWED_CHAT = "111111"


def make_update(text, chat_id=ALLOWED_CHAT):
    return {"message": {"chat": {"id": int(chat_id)}, "text": text}}


@pytest.fixture
def state(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("poll_interval_seconds: 60\nwatches: []\n")
    config = AppConfig(poll_interval_seconds=60, watches=[], path=config_path)
    return BotState(config=config)


def test_send_message_logs_api_description_without_bot_token(caplog):
    response = MagicMock()
    response.status_code = 400
    response.json.return_value = {"description": "Bad Request: chat not found"}
    response.raise_for_status.side_effect = requests.HTTPError(response=response)

    with (
        patch("ebay_bot.commands.requests.post", return_value=response),
        caplog.at_level(logging.WARNING, logger="ebay_bot.commands"),
    ):
        send_message("secret-bot-token", "chat-id", "hello")

    assert "Bad Request: chat not found" in caplog.text
    assert "secret-bot-token" not in caplog.text


def test_unauthorized_chat_is_ignored(state):
    with patch("ebay_bot.commands.send_message") as mock_send:
        handle_update(make_update("/status", chat_id="999999"), state, "tok", ALLOWED_CHAT)
    mock_send.assert_not_called()


def test_status_responds_to_authorized_chat(state):
    with patch("ebay_bot.commands.send_message") as mock_send:
        handle_update(make_update("/status"), state, "tok", ALLOWED_CHAT)
    mock_send.assert_called_once()


def test_interval_reports_current_value(state):
    with patch("ebay_bot.commands.send_message") as mock_send:
        handle_update(make_update("/interval"), state, "tok", ALLOWED_CHAT)

    assert "60s" in mock_send.call_args[0][2]


def test_interval_updates_and_persists_value(state):
    with patch("ebay_bot.commands.send_message") as mock_send:
        handle_update(make_update("/interval 120"), state, "tok", ALLOWED_CHAT)

    assert state.poll_interval == 120
    assert AppConfig.load(state.config.path).poll_interval_seconds == 120
    assert "120s" in mock_send.call_args[0][2]


@pytest.mark.parametrize("argument", ["0", "-1", "fast", "60 seconds"])
def test_interval_rejects_invalid_values(state, argument):
    with patch("ebay_bot.commands.send_message") as mock_send:
        handle_update(make_update(f"/interval {argument}"), state, "tok", ALLOWED_CHAT)

    assert state.poll_interval == 60
    assert "Usage" in mock_send.call_args[0][2]


def test_pause_and_resume(state):
    with patch("ebay_bot.commands.send_message"):
        handle_update(make_update("/pause"), state, "tok", ALLOWED_CHAT)
        assert state.paused is True
        handle_update(make_update("/resume"), state, "tok", ALLOWED_CHAT)
        assert state.paused is False


def test_addwatch_adds_and_persists(state):
    with patch("ebay_bot.commands.send_message"):
        handle_update(
            make_update("/addwatch MiniPC | mini pc | 50 | 300 | BOTH | EBAY_US"),
            state,
            "tok",
            ALLOWED_CHAT,
        )

    assert len(state.watches) == 1
    w = state.watches[0]
    assert w.name == "MiniPC"
    assert w.min_price == 50.0
    assert w.max_price == 300.0
    assert w.listing_type == "BOTH"
    assert "MiniPC" in state.pending_baseline_watch_names

    reloaded = AppConfig.load(state.config.path)
    assert len(reloaded.watches) == 1
    assert reloaded.watches[0].name == "MiniPC"


def test_addwatch_with_category_id(state):
    with patch("ebay_bot.commands.send_message"):
        handle_update(
            make_update("/addwatch PCDesktops | pc desktop | 50 | 300 | BOTH | EBAY_US | 179"),
            state,
            "tok",
            ALLOWED_CHAT,
        )
    assert state.watches[0].category_id == "179"


def test_addwatch_with_brands(state):
    with patch("ebay_bot.commands.send_message"):
        handle_update(
            make_update(
                "/addwatch MiniPC brands | mini pc | 50 | 300 | BOTH | EBAY_US | 179 | "
                "Beelink,GMKtec,Minisforum"
            ),
            state,
            "tok",
            ALLOWED_CHAT,
        )
    assert state.watches[0].category_id == "179"
    assert state.watches[0].brands == ["Beelink", "GMKtec", "Minisforum"]

    reloaded = AppConfig.load(state.config.path)
    assert reloaded.watches[0].brands == ["Beelink", "GMKtec", "Minisforum"]


def test_addwatch_brands_without_category_id_now_succeeds(state):
    # Previously required category_id (aspect_filter-based matching); no longer
    # needed now that brands feed into the q keyword search instead.
    with patch("ebay_bot.commands.send_message"):
        handle_update(
            make_update("/addwatch Bad | mini pc | 50 | 300 | BOTH | EBAY_US |  | Beelink"),
            state,
            "tok",
            ALLOWED_CHAT,
        )
    assert len(state.watches) == 1
    assert state.watches[0].category_id == ""
    assert state.watches[0].brands == ["Beelink"]


def test_malformed_addwatch_is_rejected(state):
    with patch("ebay_bot.commands.send_message") as mock_send:
        handle_update(make_update("/addwatch garbage input"), state, "tok", ALLOWED_CHAT)
    assert len(state.watches) == 0
    mock_send.assert_called_once()
    assert "Couldn't parse" in mock_send.call_args[0][2]


def test_exkeyword_adds_and_persists_for_watch(state):
    state.config.watches.append(Watch(name="MiniPC", keywords="mini pc"))

    with patch("ebay_bot.commands.send_message") as mock_send:
        handle_update(make_update("/exkeyword MiniPC | refurbished"), state, "tok", ALLOWED_CHAT)

    assert state.watches[0].exclude_keywords == ["refurbished"]
    assert AppConfig.load(state.config.path).watches[0].exclude_keywords == ["refurbished"]
    assert "refurbished" in mock_send.call_args[0][2]


def test_exkeyword_rejects_duplicate_and_malformed_arguments(state):
    state.config.watches.append(
        Watch(name="MiniPC", keywords="mini pc", exclude_keywords=["refurbished"])
    )

    with patch("ebay_bot.commands.send_message") as mock_send:
        handle_update(make_update("/exkeyword MiniPC | REfUrBiShEd"), state, "tok", ALLOWED_CHAT)
        handle_update(make_update("/exkeyword MiniPC"), state, "tok", ALLOWED_CHAT)

    assert state.watches[0].exclude_keywords == ["refurbished"]
    assert "already excluded" in mock_send.call_args_list[0].args[2]
    assert "Usage" in mock_send.call_args_list[1].args[2]


def test_removewatch(state):
    state.config.watches.append(
        Watch(name="MiniPC", keywords="mini pc", min_price=50, max_price=300)
    )
    with patch("ebay_bot.commands.send_message"):
        handle_update(make_update("/removewatch MiniPC"), state, "tok", ALLOWED_CHAT)
    assert len(state.watches) == 0
