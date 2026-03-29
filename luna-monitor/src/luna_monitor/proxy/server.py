"""Transparent reverse proxy for capturing Anthropic rate limit headers.

Sits between Claude Code and api.anthropic.com. Forwards all requests/responses
unchanged but captures rate limit utilization headers from every response.
Writes captured data to ~/.luna-monitor/rate-limits.jsonl for luna-monitor to read.

SECURITY: Never logs, stores, or inspects API keys, OAuth tokens, or request/response
bodies. Only reads rate limit headers from responses. Binds to 127.0.0.1 only.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from aiohttp import web

# ── Constants ────────────────────────────────────────────────

DEFAULT_PORT = 9120
DEFAULT_TARGET = "https://api.anthropic.com"

_RATE_LIMIT_DIR = str(Path.home() / ".luna-monitor")
_RATE_LIMIT_FILE = str(Path.home() / ".luna-monitor" / "rate-limits.jsonl")
_MAX_ENTRIES = 1000

# Headers to capture from upstream responses
_CAPTURE_HEADERS = (
    "anthropic-ratelimit-unified-5h-utilization",
    "anthropic-ratelimit-unified-7d-utilization",
    "anthropic-ratelimit-unified-5h-reset",
    "anthropic-ratelimit-unified-7d-reset",
    "anthropic-ratelimit-unified-status",
)

# Headers to NOT forward back (hop-by-hop or causes issues)
_HOP_BY_HOP = frozenset({
    "transfer-encoding", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te",
    "trailers", "upgrade",
})


# ── State ────────────────────────────────────────────────────

_start_time: float = 0.0
_requests_proxied: int = 0
_last_capture_ts: str = ""

# API health tracking
_errors_total: int = 0       # upstream 4xx/5xx count
_errors_429: int = 0         # rate limit errors specifically
_last_latency_ms: float = 0  # most recent request latency


# ── JSONL writer ─────────────────────────────────────────────

def _write_rate_limit(data: dict) -> None:
    """Append a rate limit entry to the JSONL file. Fire-and-forget."""
    try:
        os.makedirs(_RATE_LIMIT_DIR, exist_ok=True)
        line = json.dumps(data, separators=(",", ":")) + "\n"
        # O_APPEND is atomic for small writes on most filesystems
        fd = os.open(_RATE_LIMIT_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


def _rotate_jsonl() -> None:
    """Truncate rate-limits.jsonl to last _MAX_ENTRIES lines on startup."""
    try:
        with open(_RATE_LIMIT_FILE, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > _MAX_ENTRIES:
            with open(_RATE_LIMIT_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-_MAX_ENTRIES:])
    except (FileNotFoundError, OSError):
        pass


# ── Header capture ───────────────────────────────────────────

def _capture_headers(resp_headers: dict) -> dict | None:
    """Extract rate limit headers from upstream response. Returns dict or None."""
    captured = {}
    for header in _CAPTURE_HEADERS:
        val = resp_headers.get(header)
        if val is not None:
            # Map header names to short keys
            key = header.replace("anthropic-ratelimit-unified-", "").replace("-", "_")
            captured[key] = val

    if not captured:
        return None

    # Parse utilization values to float
    for k in ("5h_utilization", "7d_utilization"):
        if k in captured:
            try:
                captured[k] = float(captured[k])
            except (ValueError, TypeError):
                pass

    captured["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return captured


# ── Proxy handler ────────────────────────────────────────────

async def _proxy_handler(request: web.Request) -> web.StreamResponse:
    """Forward request to upstream and stream response back, capturing rate limit headers."""
    global _requests_proxied, _last_capture_ts, _errors_total, _errors_429, _last_latency_ms

    target_url = request.app["target"] + request.path_qs
    _requests_proxied += 1
    req_start = time.time()

    # Read request body
    body = await request.read()

    # Forward headers (excluding host, which aiohttp sets)
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host",)
    }

    try:
        async with request.app["session"].request(
            request.method,
            target_url,
            headers=fwd_headers,
            data=body,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=300),
        ) as upstream_resp:
            _last_latency_ms = (time.time() - req_start) * 1000

            # Track upstream errors
            if upstream_resp.status >= 400:
                _errors_total += 1
            if upstream_resp.status == 429:
                _errors_429 += 1

            # Capture rate limit headers
            captured = _capture_headers(upstream_resp.headers)
            if captured:
                _last_capture_ts = captured["ts"]
                _write_rate_limit(captured)

            # Build response headers (skip hop-by-hop)
            resp_headers = {
                k: v for k, v in upstream_resp.headers.items()
                if k.lower() not in _HOP_BY_HOP
            }

            # Stream response back
            response = web.StreamResponse(
                status=upstream_resp.status,
                headers=resp_headers,
            )
            await response.prepare(request)

            async for chunk in upstream_resp.content.iter_any():
                await response.write(chunk)

            await response.write_eof()
            return response

    except aiohttp.ClientError as e:
        return web.Response(status=502, text=f"Proxy error: {e}")
    except TimeoutError:
        return web.Response(status=504, text="Upstream timeout")


# ── Health endpoint ──────────────────────────────────────────

async def _health_handler(request: web.Request) -> web.Response:
    """Return proxy and upstream API health status."""
    return web.json_response({
        "status": "ok",
        "uptime_s": int(time.time() - _start_time),
        "requests_proxied": _requests_proxied,
        "last_capture_ts": _last_capture_ts,
        "api_errors_total": _errors_total,
        "api_errors_429": _errors_429,
        "last_latency_ms": round(_last_latency_ms, 1),
    })


# ── App factory ──────────────────────────────────────────────

async def _on_startup(app: web.Application) -> None:
    """Create shared HTTP session for upstream requests.

    auto_decompress=False ensures we pass raw compressed bytes through unchanged.
    Without this, aiohttp decompresses the body but we still forward the
    content-encoding header, causing the client to double-decompress (ZlibError).
    """
    app["session"] = aiohttp.ClientSession(auto_decompress=False)


async def _on_cleanup(app: web.Application) -> None:
    """Close shared HTTP session."""
    await app["session"].close()


def create_app(target: str = DEFAULT_TARGET) -> web.Application:
    """Create the proxy web application."""
    global _start_time, _requests_proxied, _errors_total, _errors_429, _last_latency_ms, _last_capture_ts
    _start_time = time.time()
    _requests_proxied = 0
    _errors_total = 0
    _errors_429 = 0
    _last_latency_ms = 0
    _last_capture_ts = ""

    _rotate_jsonl()

    app = web.Application()
    app["target"] = target.rstrip("/")
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    app.router.add_route("GET", "/health", _health_handler)
    # Catch-all for proxying
    app.router.add_route("*", "/{path_info:.*}", _proxy_handler)

    return app


def run_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT,
               target: str = DEFAULT_TARGET) -> None:
    """Start the proxy server (blocking)."""
    app = create_app(target)
    web.run_app(app, host=host, port=port, print=None)
