"""CLI entry point for luna-proxy — the rate limit header capture proxy."""

import argparse
import sys

from luna_monitor.proxy.server import DEFAULT_PORT, DEFAULT_TARGET, run_server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transparent proxy that captures Anthropic rate limit headers for luna-monitor.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--target", default=DEFAULT_TARGET,
        help=f"Upstream API URL (default: {DEFAULT_TARGET})",
    )
    args = parser.parse_args()

    print(f"luna-proxy starting on http://127.0.0.1:{args.port}")
    print(f"Forwarding to {args.target}")
    print()
    print("Add this to ~/.claude/settings.json to route Claude Code through the proxy:")
    print()
    print('  {')
    print('    "env": {')
    print(f'      "ANTHROPIC_BASE_URL": "http://127.0.0.1:{args.port}"')
    print('    }')
    print('  }')
    print()
    print("Rate limit data written to ~/.luna-monitor/rate-limits.jsonl")
    print("Press Ctrl+C to stop.")
    print()

    try:
        run_server(port=args.port, target=args.target)
    except KeyboardInterrupt:
        print("\nluna-proxy stopped.")
        sys.exit(0)
    except OSError as e:
        if "address already in use" in str(e).lower() or "10048" in str(e):
            print(f"\nError: Port {args.port} already in use. Try --port {args.port + 1}")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
