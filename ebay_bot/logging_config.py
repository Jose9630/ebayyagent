"""Configures logging to both the console and a log file (bot.log), so
activity is visible whether the bot is run in a terminal or headless."""

from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("ebay_bot")
    logger.setLevel(level)
    logger.handlers.clear()  # avoid duplicate handlers if setup_logging() is called twice

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    return logger
