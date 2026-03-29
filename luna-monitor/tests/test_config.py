"""Tests for luna_monitor.config — configuration loading."""

import json
import os
import pytest
from unittest.mock import patch

from luna_monitor.config import load_config, DEFAULTS


class TestLoadConfig:
    """load_config: loads JSON config with defaults fallback."""

    def test_returns_defaults_when_no_file(self):
        config = load_config()
        for key, val in DEFAULTS.items():
            assert config[key] == val

    def test_defaults_are_correct_types(self):
        config = load_config()
        assert isinstance(config["refresh_seconds"], float)
        assert isinstance(config["cache_ttl_seconds"], int)
        assert isinstance(config["drives"], list)
        assert isinstance(config["gpu_enabled"], bool)
        assert isinstance(config["claude_enabled"], bool)

    def test_user_config_overrides_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"refresh_seconds": 5.0, "cache_ttl_seconds": 10}))

        with patch("luna_monitor.config._config_path", return_value=str(cfg_file)):
            config = load_config()

        assert config["refresh_seconds"] == 5.0
        assert config["cache_ttl_seconds"] == 10
        # Other defaults preserved
        assert config["gpu_enabled"] is True

    def test_partial_user_config(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"drives": ["C:\\"]}))

        with patch("luna_monitor.config._config_path", return_value=str(cfg_file)):
            config = load_config()

        assert config["drives"] == ["C:\\"]
        assert config["refresh_seconds"] == 2.0  # default preserved

    def test_invalid_json_falls_back_to_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("not json at all {{{")

        with patch("luna_monitor.config._config_path", return_value=str(cfg_file)):
            config = load_config()

        assert config == DEFAULTS

    def test_non_dict_json_falls_back_to_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('"just a string"')

        with patch("luna_monitor.config._config_path", return_value=str(cfg_file)):
            config = load_config()

        assert config == DEFAULTS

    def test_missing_file_falls_back_to_defaults(self):
        with patch("luna_monitor.config._config_path", return_value="/nonexistent/path/config.json"):
            config = load_config()

        assert config == DEFAULTS

    def test_extra_keys_preserved(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"custom_key": "hello"}))

        with patch("luna_monitor.config._config_path", return_value=str(cfg_file)):
            config = load_config()

        assert config["custom_key"] == "hello"
        assert config["refresh_seconds"] == 2.0  # defaults still there
