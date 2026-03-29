"""Entry point for luna-monitor CLI."""

import argparse
import json
import sys

from luna_monitor.app import run
from luna_monitor.config import load_config


def parse_args():
    parser = argparse.ArgumentParser(
        prog="luna-monitor",
        description="Terminal dashboard for Claude Code developers",
    )
    parser.add_argument(
        "--no-gpu", action="store_true", help="Disable GPU panel"
    )
    parser.add_argument(
        "--no-claude", action="store_true", help="Disable Claude usage panels"
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=None,
        help="Refresh interval in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Disable all network requests (Claude API)",
    )
    parser.add_argument(
        "--enable-proxy",
        action="store_true",
        help="Enable the rate limit proxy (modifies ~/.claude/settings.json)",
    )
    parser.add_argument(
        "--disable-proxy",
        action="store_true",
        help="Disable the rate limit proxy and restore settings.json",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__import__('luna_monitor').__version__}",
    )
    return parser.parse_args()


def _save_proxy_choice(enabled: bool) -> None:
    """Persist proxy choice to luna-monitor config."""
    from pathlib import Path
    config_path = Path.home() / ".luna-monitor" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    config["proxy_enabled"] = enabled
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _first_run_prompt() -> bool:
    """Ask user if they want to enable the proxy. Returns True if yes."""
    print()
    print("luna-monitor can show live Claude Code usage (session %, weekly %,")
    print("time remaining) by routing API calls through a local proxy.")
    print()
    try:
        answer = input("Enable live usage tracking? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("", "y", "yes")


def _setup_proxy(config: dict) -> None:
    """Handle proxy lifecycle: crash recovery, first-run, start/stop."""
    from luna_monitor.proxy import lifecycle

    # Crash recovery: clean up stale config from a previous crash
    if lifecycle.recover_from_crash():
        print("Cleaned up stale proxy config from previous session.")

    proxy_enabled = config.get("proxy_enabled")

    # First run: ask user
    if proxy_enabled is None:
        proxy_enabled = _first_run_prompt()
        _save_proxy_choice(proxy_enabled)
        config["proxy_enabled"] = proxy_enabled

    if not proxy_enabled:
        return

    port = config.get("proxy_port", 9120)

    # Start proxy
    if lifecycle.start_proxy(port=port):
        actual_port = lifecycle.get_proxy_port()
        lifecycle.write_proxy_setting(actual_port)
        lifecycle.write_lockfile()
        lifecycle.install_cleanup_handlers()
        config["_proxy_running"] = True
        config["_proxy_port"] = actual_port

        # Start watchdog
        from luna_monitor.proxy.watchdog import start_watchdog
        start_watchdog()
    else:
        print("Warning: Could not start proxy. Running without live usage data.")
        config["_proxy_running"] = False


def main():
    args = parse_args()

    # Handle --enable-proxy / --disable-proxy
    if args.enable_proxy:
        _save_proxy_choice(True)
        from luna_monitor.proxy.lifecycle import write_proxy_setting
        port = 9120
        write_proxy_setting(port)
        print(f"Proxy enabled. ANTHROPIC_BASE_URL set to http://127.0.0.1:{port}")
        print("Run 'luna-monitor' to start the dashboard with live usage tracking.")
        return

    if args.disable_proxy:
        _save_proxy_choice(False)
        from luna_monitor.proxy.lifecycle import remove_proxy_setting, remove_lockfile
        remove_proxy_setting()
        remove_lockfile()
        print("Proxy disabled. ANTHROPIC_BASE_URL removed from settings.json.")
        return

    config = load_config()

    # CLI flags override config
    if args.refresh is not None:
        config["refresh_seconds"] = args.refresh
    if args.no_gpu:
        config["gpu_enabled"] = False
    if args.no_claude or args.offline:
        config["claude_enabled"] = False

    # Proxy lifecycle (unless Claude panels are disabled)
    if config.get("claude_enabled", True) and not args.offline:
        _setup_proxy(config)

    try:
        run(config)
    except KeyboardInterrupt:
        pass
    finally:
        # Ensure cleanup runs even if run() throws
        if config.get("_proxy_running"):
            from luna_monitor.proxy.lifecycle import cleanup
            cleanup()


if __name__ == "__main__":
    main()
