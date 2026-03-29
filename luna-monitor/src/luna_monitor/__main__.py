"""Entry point for luna-monitor CLI."""

import argparse
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
        "--version",
        action="version",
        version=f"%(prog)s {__import__('luna_monitor').__version__}",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()

    # CLI flags override config
    if args.refresh is not None:
        config["refresh_seconds"] = args.refresh
    if args.no_gpu:
        config["gpu_enabled"] = False
    if args.no_claude or args.offline:
        config["claude_enabled"] = False

    try:
        run(config)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
