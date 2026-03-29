"""Watchdog thread — monitors proxy health, auto-restarts on failure.

Checks the proxy /health endpoint every 2 seconds. If it fails, restarts
the proxy immediately. After 3 consecutive failures, sets a flag so the
dashboard can show "Proxy: restarting..." to the user.
"""

import threading
import time

from luna_monitor.proxy.lifecycle import is_proxy_healthy, restart_proxy

# ── State (read by dashboard) ────────────────────────────────

consecutive_failures: int = 0
is_recovering: bool = False
last_check_time: float = 0.0

_CHECK_INTERVAL: float = 2.0
_FAILURE_THRESHOLD: int = 3
_stop_event = threading.Event()


# ── Watchdog thread ──────────────────────────────────────────

def _watchdog_loop() -> None:
    """Main watchdog loop. Runs in a daemon thread."""
    global consecutive_failures, is_recovering, last_check_time

    while not _stop_event.is_set():
        _stop_event.wait(_CHECK_INTERVAL)
        if _stop_event.is_set():
            break

        last_check_time = time.time()

        if is_proxy_healthy():
            if consecutive_failures > 0:
                consecutive_failures = 0
                is_recovering = False
        else:
            consecutive_failures += 1

            if consecutive_failures >= _FAILURE_THRESHOLD:
                is_recovering = True

            # Attempt restart on every failure
            if restart_proxy():
                consecutive_failures = 0
                is_recovering = False


def start_watchdog() -> threading.Thread:
    """Start the watchdog in a daemon thread. Returns the thread."""
    _stop_event.clear()
    t = threading.Thread(target=_watchdog_loop, daemon=True, name="luna-watchdog")
    t.start()
    return t


def stop_watchdog() -> None:
    """Stop the watchdog thread."""
    _stop_event.set()
