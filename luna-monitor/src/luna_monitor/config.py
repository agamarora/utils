"""Configuration loading with sensible defaults."""

import json
import os
import sys

DEFAULTS = {
    "refresh_seconds": 2.0,
    "cache_ttl_seconds": 30,
    "drives": ["C:\\", "D:\\"],
    "gpu_enabled": True,
    "claude_enabled": True,
}


def _config_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "luna-monitor", "config.json")
    return os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "luna-monitor",
        "config.json",
    )


def load_config() -> dict:
    """Load config from disk, falling back to defaults for missing keys."""
    config = dict(DEFAULTS)
    path = _config_path()
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            config.update(user)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return config
