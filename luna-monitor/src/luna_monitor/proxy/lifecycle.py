"""Proxy lifecycle management — start/stop proxy thread, settings.json, lockfile.

Manages the embedded proxy as a daemon thread with its own asyncio event loop.
Handles settings.json read-parse-merge with atomic writes and crash recovery.

RULES for settings.json:
1. Always read before write — never overwrite the whole file
2. Atomic write — temp file + rename
3. Backup on first write — ~/.luna-monitor/settings.json.backup
4. Only touch env.ANTHROPIC_BASE_URL — nothing else
"""

import asyncio
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from luna_monitor.proxy.server import create_app, DEFAULT_PORT, DEFAULT_TARGET

# ── Constants ────────────────────────────────────────────────

_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_LUNA_DIR = Path.home() / ".luna-monitor"
_BACKUP_PATH = _LUNA_DIR / "settings.json.backup"
_LOCKFILE_PATH = _LUNA_DIR / "proxy.pid"

# ── State ────────────────────────────────────────────────────

_proxy_thread: threading.Thread | None = None
_proxy_loop: asyncio.AbstractEventLoop | None = None
_proxy_runner: object | None = None  # web.AppRunner
_proxy_port: int = DEFAULT_PORT
_last_start_error: str | None = None


# ── Settings.json management ─────────────────────────────────

def _read_settings() -> dict:
    """Read and parse settings.json. Returns empty dict if missing/invalid."""
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_settings_atomic(settings: dict) -> bool:
    """Write settings dict to settings.json atomically. Returns True on success."""
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        tmp.replace(_SETTINGS_PATH)
        return True
    except OSError:
        return False


def write_proxy_setting(port: int) -> bool:
    """Add ANTHROPIC_BASE_URL to settings.json, preserving all other settings."""
    settings = _read_settings()

    # Backup on first modification
    _LUNA_DIR.mkdir(parents=True, exist_ok=True)
    if not _BACKUP_PATH.exists():
        try:
            _BACKUP_PATH.write_text(
                json.dumps(settings, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    env = settings.setdefault("env", {})
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    return _write_settings_atomic(settings)


def remove_proxy_setting() -> bool:
    """Remove ANTHROPIC_BASE_URL from settings.json, preserving everything else."""
    settings = _read_settings()
    env = settings.get("env", {})
    if "ANTHROPIC_BASE_URL" not in env:
        return True

    del env["ANTHROPIC_BASE_URL"]
    if not env:
        settings.pop("env", None)

    return _write_settings_atomic(settings)


def has_proxy_setting() -> bool:
    """Check if ANTHROPIC_BASE_URL is set in settings.json."""
    settings = _read_settings()
    return "ANTHROPIC_BASE_URL" in settings.get("env", {})


# ── Lockfile (PID-based crash detection) ─────────────────────

def write_lockfile() -> None:
    """Write current PID to lockfile."""
    try:
        _LUNA_DIR.mkdir(parents=True, exist_ok=True)
        _LOCKFILE_PATH.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def remove_lockfile() -> None:
    """Remove lockfile."""
    try:
        _LOCKFILE_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def check_stale_lockfile() -> bool:
    """Check if a stale lockfile exists (previous crash). Returns True if stale."""
    try:
        pid_str = _LOCKFILE_PATH.read_text(encoding="utf-8").strip()
        pid = int(pid_str)
    except (FileNotFoundError, ValueError, OSError):
        return False

    # Check if PID is still alive
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return False  # process is alive, not stale
        return True  # process is dead, stale lockfile
    else:
        try:
            os.kill(pid, 0)
            return False  # process is alive
        except ProcessLookupError:
            return True  # process is dead
        except PermissionError:
            return False  # process exists but we can't signal it


def recover_from_crash() -> bool:
    """Clean up stale proxy config from a previous crash. Returns True if cleanup was done."""
    if check_stale_lockfile():
        remove_proxy_setting()
        remove_lockfile()
        return True
    return False


# ── Proxy thread management ──────────────────────────────────

def _run_proxy_loop(port: int, target: str) -> None:
    """Entry point for the proxy daemon thread. Runs its own event loop."""
    global _proxy_loop, _proxy_runner, _last_start_error

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _proxy_loop = loop

    async def _start():
        global _proxy_runner
        from aiohttp import web
        app = create_app(target)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        _proxy_runner = runner
        # Keep the loop running until stopped
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()

    try:
        loop.run_until_complete(_start())
    except Exception as e:
        _last_start_error = str(e)
    finally:
        loop.close()
        _proxy_loop = None


def start_proxy(port: int = DEFAULT_PORT, target: str = DEFAULT_TARGET) -> bool:
    """Start the proxy in a daemon thread. Returns True on success."""
    global _proxy_thread, _proxy_port

    _proxy_port = port

    # Try the requested port, fall back to next ports if in use
    for p in range(port, port + 10):
        try:
            _proxy_thread = threading.Thread(
                target=_run_proxy_loop,
                args=(p, target),
                daemon=True,
                name="luna-proxy",
            )
            _proxy_thread.start()

            # Wait briefly for the thread to start and bind
            for _ in range(20):
                time.sleep(0.1)
                if is_proxy_healthy(p):
                    _proxy_port = p
                    return True

            # Thread started but health check failed, try next port
            stop_proxy()
        except OSError:
            continue

    return False


def stop_proxy() -> None:
    """Stop the proxy thread gracefully."""
    global _proxy_thread, _proxy_loop, _proxy_runner

    if _proxy_loop and _proxy_loop.is_running():
        # Cancel all tasks in the proxy loop
        for task in asyncio.all_tasks(_proxy_loop):
            _proxy_loop.call_soon_threadsafe(task.cancel)

    if _proxy_thread and _proxy_thread.is_alive():
        _proxy_thread.join(timeout=3.0)

    _proxy_thread = None
    _proxy_loop = None
    _proxy_runner = None


def restart_proxy(port: int | None = None, target: str = DEFAULT_TARGET) -> bool:
    """Stop and restart the proxy. Returns True on success."""
    stop_proxy()
    return start_proxy(port=port or _proxy_port, target=target)


def is_proxy_healthy(port: int | None = None) -> bool:
    """Check proxy health via GET /health. Returns True if healthy."""
    p = port or _proxy_port
    try:
        import urllib.request
        with urllib.request.urlopen(
            f"http://127.0.0.1:{p}/health", timeout=1
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_proxy_port() -> int:
    """Return the port the proxy is running on."""
    return _proxy_port


def get_last_error() -> str | None:
    """Return the last proxy start error, if any."""
    return _last_start_error


# ── Cleanup handlers ─────────────────────────────────────────

_cleanup_done = False


def cleanup() -> None:
    """Remove proxy setting and lockfile. Safe to call multiple times."""
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    stop_proxy()
    remove_proxy_setting()
    remove_lockfile()


def install_cleanup_handlers() -> None:
    """Install atexit and signal handlers for clean shutdown."""
    import atexit
    atexit.register(cleanup)

    def _signal_handler(signum, frame):
        cleanup()
        sys.exit(0)

    # SIGINT (Ctrl+C) and SIGTERM
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
