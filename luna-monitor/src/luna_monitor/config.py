"""Configuration loading with sensible defaults."""

import json
import os

DEFAULTS = {
    "refresh_seconds": 2.0,
    "cache_ttl_seconds": 30,
    "drives": ["C:\\", "D:\\"],
    "gpu_enabled": True,
    "claude_enabled": True,
    "proxy_enabled": None,  # None = not yet decided, True/False = user choice
    "proxy_port": 9120,
}


def _config_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".luna-monitor", "config.json")


def load_config() -> dict:
    """Load config from ~/.luna-monitor/config.json, falling back to defaults.

    Validates values to prevent crashes from bad config (e.g., zero refresh).
    """
    config = dict(DEFAULTS)
    path = _config_path()
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            config.update(user)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    # Clamp values to safe ranges
    config["refresh_seconds"] = max(0.5, float(config.get("refresh_seconds", 2.0)))
    config["cache_ttl_seconds"] = max(5, int(config.get("cache_ttl_seconds", 30)))
    if not isinstance(config.get("drives"), list):
        config["drives"] = DEFAULTS["drives"]

    return config
