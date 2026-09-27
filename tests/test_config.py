import pytest

from ebay_bot.config import AppConfig, Watch
from ebay_bot.main import _load_config


def test_watch_rejects_min_greater_than_max():
    with pytest.raises(ValueError, match="min_price"):
        Watch(name="x", keywords="y", min_price=300, max_price=50)


def test_watch_rejects_invalid_listing_type():
    with pytest.raises(ValueError, match="listing_type"):
        Watch(name="x", keywords="y", listing_type="WEIRD")


def test_watch_normalizes_listing_type_case():
    w = Watch(name="x", keywords="y", listing_type="both")
    assert w.listing_type == "BOTH"


def test_watch_rejects_empty_name():
    with pytest.raises(ValueError, match="name"):
        Watch(name="  ", keywords="y")


def test_watch_accepts_brands_without_category_id(caplog):
    # No longer required now that brands feed into the q keyword search
    # instead of eBay's structured aspect_filter - but should warn, since an
    # unscoped brand search matches anywhere on eBay, not just the right category.
    with caplog.at_level("WARNING"):
        w = Watch(name="x", keywords="", brands=["Beelink", "GMKtec"])
    assert w.brands == ["Beelink", "GMKtec"]
    assert any("category_id" in record.message for record in caplog.records)


def test_watch_with_brands_and_category_id_does_not_warn(caplog):
    with caplog.at_level("WARNING"):
        Watch(name="x", keywords="", category_id="179", brands=["Beelink"])
    assert not any("category_id" in record.message for record in caplog.records)


def test_watch_accepts_brands_with_category_id():
    w = Watch(name="x", keywords="mini pc", category_id="179", brands=["Beelink", "GMKtec"])
    assert w.brands == ["Beelink", "GMKtec"]


def test_watch_rejects_no_keywords_no_category_id_no_brands():
    with pytest.raises(ValueError, match="no keywords, category_id, or brands"):
        Watch(name="x", keywords="")


def test_watch_accepts_brands_alone_with_no_keywords_or_category_id():
    # brands alone satisfies eBay's "must have q or category_ids" requirement,
    # since brands populates the q parameter.
    w = Watch(name="x", keywords="", brands=["Beelink"])
    assert w.category_id == ""


def test_watch_accepts_empty_keywords_with_category_id():
    # category_id alone satisfies eBay's "must have q or category_ids" requirement
    w = Watch(name="x", keywords="", category_id="179")
    assert w.keywords == ""


def test_appconfig_uses_default_poll_interval_of_40_when_missing(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("watches: []\n")

    config = AppConfig.load(config_path)

    assert config.poll_interval_seconds == 40


def test_appconfig_loads_from_yaml(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "poll_interval_seconds: 90\n"
        "watches:\n"
        "  - name: MiniPC\n"
        "    keywords: mini pc\n"
        "    min_price: 50\n"
        "    max_price: 300\n"
        "    listing_type: BOTH\n"
    )
    config = AppConfig.load(config_path)
    assert config.poll_interval_seconds == 90
    assert len(config.watches) == 1
    assert config.watches[0].name == "MiniPC"
    assert config.watches[0].min_price == 50


def test_appconfig_save_watches_persists_changes(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("poll_interval_seconds: 60\nwatches: []\n")
    config = AppConfig.load(config_path)
    config.watches.append(Watch(name="New", keywords="thing"))
    config.save_watches()

    reloaded = AppConfig.load(config_path)
    assert len(reloaded.watches) == 1
    assert reloaded.watches[0].name == "New"


def test_load_config_seeds_custom_path_from_bundled_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "poll_interval_seconds: 90\nwatches:\n  - name: MiniPC\n    keywords: mini pc\n"
    )
    config_path = tmp_path / "data" / "config.yaml"
    monkeypatch.setenv("CONFIG_PATH", str(config_path))

    config = _load_config()

    assert config.path == config_path
    assert config.poll_interval_seconds == 90
    assert config_path.is_file()
