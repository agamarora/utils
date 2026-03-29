"""Tests for proxy/lifecycle.py — settings.json management, lockfile, proxy thread."""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from luna_monitor.proxy import lifecycle


# ── Settings.json tests ──────────────────────────────────────

class TestWriteProxySetting:
    def test_creates_env_block(self, tmp_path):
        """Creates env.ANTHROPIC_BASE_URL in empty settings."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{}")
        backup_path = tmp_path / "backup.json"

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path), \
             patch.object(lifecycle, "_BACKUP_PATH", backup_path), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            result = lifecycle.write_proxy_setting(9120)

        assert result is True
        settings = json.loads(settings_path.read_text())
        assert settings["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9120"

    def test_preserves_existing_settings(self, tmp_path):
        """Existing settings are preserved when adding proxy."""
        settings_path = tmp_path / "settings.json"
        original = {
            "statusLine": {"type": "command", "command": "some-command"},
            "hooks": {"Stop": []},
        }
        settings_path.write_text(json.dumps(original))
        backup_path = tmp_path / "backup.json"

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path), \
             patch.object(lifecycle, "_BACKUP_PATH", backup_path), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            lifecycle.write_proxy_setting(9120)

        settings = json.loads(settings_path.read_text())
        assert settings["statusLine"] == original["statusLine"]
        assert settings["hooks"] == original["hooks"]
        assert settings["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9120"

    def test_preserves_existing_env_vars(self, tmp_path):
        """Other env vars in the env block are preserved."""
        settings_path = tmp_path / "settings.json"
        original = {"env": {"OTHER_VAR": "keep-me"}}
        settings_path.write_text(json.dumps(original))
        backup_path = tmp_path / "backup.json"

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path), \
             patch.object(lifecycle, "_BACKUP_PATH", backup_path), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            lifecycle.write_proxy_setting(9120)

        settings = json.loads(settings_path.read_text())
        assert settings["env"]["OTHER_VAR"] == "keep-me"
        assert settings["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9120"

    def test_creates_backup_on_first_write(self, tmp_path):
        """Backup is created on first modification."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"existing": true}')
        backup_path = tmp_path / "backup.json"

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path), \
             patch.object(lifecycle, "_BACKUP_PATH", backup_path), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            lifecycle.write_proxy_setting(9120)

        assert backup_path.exists()
        backup = json.loads(backup_path.read_text())
        assert backup["existing"] is True
        assert "env" not in backup  # backup is BEFORE modification

    def test_does_not_overwrite_existing_backup(self, tmp_path):
        """Second write does not overwrite the first backup."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{}")
        backup_path = tmp_path / "backup.json"
        backup_path.write_text('{"original": "backup"}')

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path), \
             patch.object(lifecycle, "_BACKUP_PATH", backup_path), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            lifecycle.write_proxy_setting(9999)

        backup = json.loads(backup_path.read_text())
        assert backup["original"] == "backup"  # unchanged

    def test_creates_settings_if_missing(self, tmp_path):
        """Creates settings.json if it doesn't exist."""
        settings_path = tmp_path / ".claude" / "settings.json"
        backup_path = tmp_path / "backup.json"

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path), \
             patch.object(lifecycle, "_BACKUP_PATH", backup_path), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            result = lifecycle.write_proxy_setting(9120)

        assert result is True
        assert settings_path.exists()

    def test_custom_port(self, tmp_path):
        """Port number is reflected in the URL."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{}")
        backup_path = tmp_path / "backup.json"

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path), \
             patch.object(lifecycle, "_BACKUP_PATH", backup_path), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            lifecycle.write_proxy_setting(9125)

        settings = json.loads(settings_path.read_text())
        assert "9125" in settings["env"]["ANTHROPIC_BASE_URL"]


class TestRemoveProxySetting:
    def test_removes_base_url(self, tmp_path):
        """Removes ANTHROPIC_BASE_URL from settings."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9120", "OTHER": "keep"},
            "hooks": {},
        }))

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path):
            result = lifecycle.remove_proxy_setting()

        assert result is True
        settings = json.loads(settings_path.read_text())
        assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})
        assert settings["env"]["OTHER"] == "keep"
        assert "hooks" in settings

    def test_removes_empty_env_block(self, tmp_path):
        """Removes env block entirely if it becomes empty."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9120"},
            "hooks": {},
        }))

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path):
            lifecycle.remove_proxy_setting()

        settings = json.loads(settings_path.read_text())
        assert "env" not in settings
        assert "hooks" in settings

    def test_noop_when_not_set(self, tmp_path):
        """Returns True and does nothing when ANTHROPIC_BASE_URL not present."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"hooks": {}}')

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path):
            result = lifecycle.remove_proxy_setting()

        assert result is True

    def test_noop_when_file_missing(self, tmp_path):
        """Returns True when settings.json doesn't exist."""
        with patch.object(lifecycle, "_SETTINGS_PATH", tmp_path / "missing.json"):
            result = lifecycle.remove_proxy_setting()
        assert result is True

    def test_roundtrip(self, tmp_path):
        """Write then remove restores original state."""
        settings_path = tmp_path / "settings.json"
        original = {"statusLine": {"type": "command"}, "hooks": {"Stop": []}}
        settings_path.write_text(json.dumps(original))
        backup_path = tmp_path / "backup.json"

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path), \
             patch.object(lifecycle, "_BACKUP_PATH", backup_path), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            lifecycle.write_proxy_setting(9120)
            lifecycle.remove_proxy_setting()

        settings = json.loads(settings_path.read_text())
        assert settings == original


# ── Lockfile tests ───────────────────────────────────────────

class TestLockfile:
    def test_write_and_read(self, tmp_path):
        """Lockfile contains current PID."""
        lockfile = tmp_path / "proxy.pid"
        with patch.object(lifecycle, "_LOCKFILE_PATH", lockfile), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            lifecycle.write_lockfile()

        assert lockfile.exists()
        assert int(lockfile.read_text()) == os.getpid()

    def test_remove(self, tmp_path):
        """Lockfile is removed."""
        lockfile = tmp_path / "proxy.pid"
        lockfile.write_text("12345")
        with patch.object(lifecycle, "_LOCKFILE_PATH", lockfile):
            lifecycle.remove_lockfile()
        assert not lockfile.exists()

    def test_remove_missing(self, tmp_path):
        """Removing nonexistent lockfile doesn't error."""
        with patch.object(lifecycle, "_LOCKFILE_PATH", tmp_path / "missing.pid"):
            lifecycle.remove_lockfile()  # should not raise

    def test_stale_detection_dead_process(self, tmp_path):
        """Detects stale lockfile when PID is dead."""
        lockfile = tmp_path / "proxy.pid"
        lockfile.write_text("999999999")  # very unlikely to be a real PID

        with patch.object(lifecycle, "_LOCKFILE_PATH", lockfile):
            assert lifecycle.check_stale_lockfile() is True

    def test_stale_detection_alive_process(self, tmp_path):
        """Does not detect stale when PID is current process (alive)."""
        lockfile = tmp_path / "proxy.pid"
        lockfile.write_text(str(os.getpid()))

        with patch.object(lifecycle, "_LOCKFILE_PATH", lockfile):
            assert lifecycle.check_stale_lockfile() is False

    def test_stale_detection_no_lockfile(self, tmp_path):
        """No lockfile = not stale."""
        with patch.object(lifecycle, "_LOCKFILE_PATH", tmp_path / "missing.pid"):
            assert lifecycle.check_stale_lockfile() is False


class TestCrashRecovery:
    def test_cleans_stale_config(self, tmp_path):
        """Crash recovery removes stale ANTHROPIC_BASE_URL and lockfile."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9120"},
        }))
        lockfile = tmp_path / "proxy.pid"
        lockfile.write_text("999999999")

        with patch.object(lifecycle, "_SETTINGS_PATH", settings_path), \
             patch.object(lifecycle, "_LOCKFILE_PATH", lockfile), \
             patch.object(lifecycle, "_LUNA_DIR", tmp_path):
            result = lifecycle.recover_from_crash()

        assert result is True
        assert not lockfile.exists()
        settings = json.loads(settings_path.read_text())
        assert "ANTHROPIC_BASE_URL" not in settings.get("env", {})

    def test_no_crash_no_cleanup(self, tmp_path):
        """No stale lockfile = no cleanup needed."""
        with patch.object(lifecycle, "_LOCKFILE_PATH", tmp_path / "missing.pid"):
            result = lifecycle.recover_from_crash()
        assert result is False


# ── Proxy health check ───────────────────────────────────────

class TestIsProxyHealthy:
    def test_healthy(self):
        """Returns True when health endpoint responds 200."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert lifecycle.is_proxy_healthy(9120) is True

    def test_unhealthy(self):
        """Returns False when connection fails."""
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError):
            assert lifecycle.is_proxy_healthy(9120) is False
