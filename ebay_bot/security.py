"""Best-effort security check for the .env file's permissions (POSIX only).
Never blocks startup - just logs a warning so credentials aren't left
readable by other users on shared/multi-user machines."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger("ebay_bot")


def warn_if_env_permissions_insecure(env_path: str | Path = ".env") -> None:
    if os.name == "nt":
        return  # Windows' permission model is different; nothing to check here.

    path = Path(env_path)
    if not path.exists():
        return

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:  # group or other have any read/write/execute permission
        logger.warning(
            f"{path} is readable by other users on this system (mode {oct(mode)}). "
            f"It contains your eBay/Telegram credentials - consider restricting it "
            f"with: chmod 600 {path}"
        )
