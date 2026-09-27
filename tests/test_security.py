import os
import stat

import pytest

from ebay_bot.security import warn_if_env_permissions_insecure

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="permission bits work differently on Windows"
)


def test_warns_when_env_is_group_or_world_readable(tmp_path, caplog):
    env_path = tmp_path / ".env"
    env_path.write_text("EBAY_CLIENT_ID=x\n")
    env_path.chmod(0o644)  # world-readable

    with caplog.at_level("WARNING"):
        warn_if_env_permissions_insecure(env_path)

    assert any("chmod 600" in record.message for record in caplog.records)


def test_no_warning_when_env_is_owner_only(tmp_path, caplog):
    env_path = tmp_path / ".env"
    env_path.write_text("EBAY_CLIENT_ID=x\n")
    env_path.chmod(0o600)  # owner read/write only

    with caplog.at_level("WARNING"):
        warn_if_env_permissions_insecure(env_path)

    assert not any("chmod 600" in record.message for record in caplog.records)


def test_no_error_when_env_file_missing(tmp_path):
    missing_path = tmp_path / ".env"
    warn_if_env_permissions_insecure(missing_path)  # should not raise


def test_mode_bits_detected_correctly(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("x")
    env_path.chmod(0o600)
    mode = stat.S_IMODE(env_path.stat().st_mode)
    assert mode & 0o077 == 0
