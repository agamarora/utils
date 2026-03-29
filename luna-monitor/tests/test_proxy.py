"""Tests for proxy/server.py — reverse proxy with header capture."""

import json
import os
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
import pytest_asyncio
import aiohttp
from aiohttp import web

from luna_monitor.proxy.server import (
    create_app,
    _capture_headers,
    _write_rate_limit,
    _rotate_jsonl,
    _health_handler,
    DEFAULT_TARGET,
)


# ── Header capture tests ────────────────────────────────────

class TestCaptureHeaders:
    def test_captures_all_headers(self):
        """Extracts all rate limit headers from response."""
        headers = {
            "anthropic-ratelimit-unified-5h-utilization": "0.42",
            "anthropic-ratelimit-unified-7d-utilization": "0.15",
            "anthropic-ratelimit-unified-5h-reset": "2026-03-29T22:30:00Z",
            "anthropic-ratelimit-unified-7d-reset": "2026-04-05T00:00:00Z",
            "anthropic-ratelimit-unified-status": "ok",
            "content-type": "text/event-stream",  # should be ignored
        }
        result = _capture_headers(headers)

        assert result is not None
        assert result["5h_utilization"] == 0.42
        assert result["7d_utilization"] == 0.15
        assert result["5h_reset"] == "2026-03-29T22:30:00Z"
        assert result["7d_reset"] == "2026-04-05T00:00:00Z"
        assert result["status"] == "ok"
        assert "ts" in result

    def test_returns_none_when_no_headers(self):
        """Returns None when no rate limit headers present."""
        headers = {"content-type": "application/json", "x-request-id": "abc"}
        result = _capture_headers(headers)
        assert result is None

    def test_partial_headers(self):
        """Captures whatever headers are available."""
        headers = {"anthropic-ratelimit-unified-5h-utilization": "0.33"}
        result = _capture_headers(headers)
        assert result is not None
        assert result["5h_utilization"] == 0.33
        assert "7d_utilization" not in result

    def test_non_numeric_utilization(self):
        """Non-numeric utilization kept as string."""
        headers = {"anthropic-ratelimit-unified-5h-utilization": "not_a_number"}
        result = _capture_headers(headers)
        assert result is not None
        # Conversion failed, kept as-is
        assert result["5h_utilization"] == "not_a_number"


# ── JSONL write tests ────────────────────────────────────────

class TestWriteRateLimit:
    def test_writes_to_file(self, tmp_path):
        """Writes valid JSONL entry to file."""
        jf = tmp_path / "rate-limits.jsonl"
        data = {"ts": "2026-03-29T17:30:00Z", "5h_utilization": 0.42}

        with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", str(jf)), \
             patch("luna_monitor.proxy.server._RATE_LIMIT_DIR", str(tmp_path)):
            _write_rate_limit(data)

        content = jf.read_text()
        parsed = json.loads(content.strip())
        assert parsed["5h_utilization"] == 0.42

    def test_appends_multiple(self, tmp_path):
        """Multiple writes append, not overwrite."""
        jf = tmp_path / "rate-limits.jsonl"

        with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", str(jf)), \
             patch("luna_monitor.proxy.server._RATE_LIMIT_DIR", str(tmp_path)):
            _write_rate_limit({"entry": 1})
            _write_rate_limit({"entry": 2})

        lines = jf.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_creates_directory(self, tmp_path):
        """Creates parent directory if it doesn't exist."""
        sub = tmp_path / "subdir"
        jf = sub / "rate-limits.jsonl"

        with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", str(jf)), \
             patch("luna_monitor.proxy.server._RATE_LIMIT_DIR", str(sub)):
            _write_rate_limit({"test": True})

        assert jf.exists()


# ── JSONL rotation tests ─────────────────────────────────────

class TestRotateJsonl:
    def test_truncates_when_over_limit(self, tmp_path):
        """Keeps only last _MAX_ENTRIES lines."""
        jf = tmp_path / "rate-limits.jsonl"
        lines = [json.dumps({"i": i}) + "\n" for i in range(1500)]
        jf.write_text("".join(lines))

        with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", str(jf)), \
             patch("luna_monitor.proxy.server._MAX_ENTRIES", 1000):
            _rotate_jsonl()

        remaining = jf.read_text().strip().split("\n")
        assert len(remaining) == 1000
        # Should keep the LAST 1000
        first = json.loads(remaining[0])
        assert first["i"] == 500

    def test_no_truncation_when_under_limit(self, tmp_path):
        """Does nothing when file is under the limit."""
        jf = tmp_path / "rate-limits.jsonl"
        lines = [json.dumps({"i": i}) + "\n" for i in range(50)]
        jf.write_text("".join(lines))

        with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", str(jf)), \
             patch("luna_monitor.proxy.server._MAX_ENTRIES", 1000):
            _rotate_jsonl()

        remaining = jf.read_text().strip().split("\n")
        assert len(remaining) == 50

    def test_missing_file_no_error(self):
        """No error when file doesn't exist."""
        with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", "/nonexistent"):
            _rotate_jsonl()  # should not raise


# ── Health endpoint test ─────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint():
    """Health endpoint returns JSON with status and metrics."""
    import luna_monitor.proxy.server as srv
    srv._start_time = 1000.0
    srv._requests_proxied = 42
    srv._last_capture_ts = "2026-03-29T17:30:00Z"

    with patch("luna_monitor.proxy.server.time") as mock_time:
        mock_time.time.return_value = 1060.0
        request = MagicMock()
        resp = await _health_handler(request)

    body = json.loads(resp.body)
    assert body["status"] == "ok"
    assert body["uptime_s"] == 60
    assert body["requests_proxied"] == 42
    assert body["last_capture_ts"] == "2026-03-29T17:30:00Z"


# ── Proxy integration tests (using aiohttp test server) ─────

@pytest_asyncio.fixture
def upstream_app():
    """Create a mock upstream 'Anthropic API' server."""
    app = web.Application()

    async def messages_handler(request):
        """Mock /v1/messages endpoint with rate limit headers."""
        body = await request.read()
        return web.Response(
            status=200,
            body=b'{"id":"msg_123","content":"hello"}',
            headers={
                "content-type": "application/json",
                "anthropic-ratelimit-unified-5h-utilization": "0.42",
                "anthropic-ratelimit-unified-7d-utilization": "0.15",
                "anthropic-ratelimit-unified-5h-reset": "2026-03-29T22:30:00Z",
                "anthropic-ratelimit-unified-7d-reset": "2026-04-05T00:00:00Z",
                "anthropic-ratelimit-unified-status": "ok",
            },
        )

    async def sse_handler(request):
        """Mock SSE streaming endpoint."""
        resp = web.StreamResponse(
            status=200,
            headers={
                "content-type": "text/event-stream",
                "anthropic-ratelimit-unified-5h-utilization": "0.50",
            },
        )
        await resp.prepare(request)
        for i in range(3):
            await resp.write(f"data: chunk{i}\n\n".encode())
        await resp.write_eof()
        return resp

    async def error_handler(request):
        """Mock 429 error."""
        return web.Response(
            status=429,
            body=b'{"error":"rate_limited"}',
            headers={
                "content-type": "application/json",
                "anthropic-ratelimit-unified-5h-utilization": "0.99",
                "retry-after": "30",
            },
        )

    app.router.add_post("/v1/messages", messages_handler)
    app.router.add_post("/v1/messages/stream", sse_handler)
    app.router.add_post("/v1/error", error_handler)
    return app


@pytest_asyncio.fixture
async def proxy_and_upstream(aiohttp_client, upstream_app, tmp_path):
    """Start both upstream mock and proxy, return proxy client."""
    # Start upstream
    upstream_client = await aiohttp_client(upstream_app)
    upstream_url = str(upstream_client.make_url(""))

    # Create proxy targeting upstream
    proxy_app = create_app(target=upstream_url.rstrip("/"))

    # Patch JSONL output to tmp_path
    jf = tmp_path / "rate-limits.jsonl"
    with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", str(jf)), \
         patch("luna_monitor.proxy.server._RATE_LIMIT_DIR", str(tmp_path)):
        proxy_client = await aiohttp_client(proxy_app)
        yield proxy_client, jf


@pytest.mark.asyncio
async def test_proxy_forwards_request(proxy_and_upstream):
    """Proxy forwards request to upstream and returns response."""
    proxy_client, jf = proxy_and_upstream
    resp = await proxy_client.post(
        "/v1/messages",
        json={"model": "claude-opus-4-6", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["id"] == "msg_123"


@pytest.mark.asyncio
async def test_proxy_captures_headers_integration(proxy_and_upstream):
    """Proxy captures rate limit headers and writes to JSONL."""
    proxy_client, jf = proxy_and_upstream
    await proxy_client.post("/v1/messages", json={"test": True})

    # Check JSONL was written
    assert jf.exists()
    content = jf.read_text().strip()
    entry = json.loads(content)
    assert entry["5h_utilization"] == 0.42
    assert entry["7d_utilization"] == 0.15


@pytest.mark.asyncio
async def test_proxy_streams_sse(proxy_and_upstream):
    """Proxy streams SSE chunks without buffering."""
    proxy_client, jf = proxy_and_upstream
    resp = await proxy_client.post("/v1/messages/stream", json={"stream": True})
    assert resp.status == 200

    body = await resp.read()
    assert b"chunk0" in body
    assert b"chunk1" in body
    assert b"chunk2" in body


@pytest.mark.asyncio
async def test_proxy_forwards_errors(proxy_and_upstream):
    """Proxy forwards upstream errors (429) as-is, still captures headers."""
    proxy_client, jf = proxy_and_upstream
    resp = await proxy_client.post("/v1/error", json={"test": True})
    assert resp.status == 429

    # Headers should still be captured
    assert jf.exists()
    entry = json.loads(jf.read_text().strip())
    assert entry["5h_utilization"] == 0.99


@pytest.mark.asyncio
async def test_proxy_no_headers_no_write(aiohttp_client, tmp_path):
    """When upstream has no rate limit headers, no JSONL entry is written."""
    # Upstream with no rate limit headers
    upstream = web.Application()

    async def bare_handler(request):
        return web.Response(status=200, body=b"ok")

    upstream.router.add_post("/v1/bare", bare_handler)
    upstream_client = await aiohttp_client(upstream)

    proxy_app = create_app(target=str(upstream_client.make_url("")).rstrip("/"))
    jf = tmp_path / "rate-limits.jsonl"

    with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", str(jf)), \
         patch("luna_monitor.proxy.server._RATE_LIMIT_DIR", str(tmp_path)):
        proxy_client = await aiohttp_client(proxy_app)
        await proxy_client.post("/v1/bare", json={})

    assert not jf.exists()


@pytest.mark.asyncio
async def test_health_endpoint_integration(aiohttp_client, tmp_path):
    """Health endpoint works through the proxy app."""
    proxy_app = create_app(target="http://localhost:1")  # target doesn't matter for /health

    with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", str(tmp_path / "rl.jsonl")), \
         patch("luna_monitor.proxy.server._RATE_LIMIT_DIR", str(tmp_path)):
        client = await aiohttp_client(proxy_app)
        resp = await client.get("/health")

    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"
    assert "uptime_s" in body
    assert "requests_proxied" in body


@pytest.mark.asyncio
async def test_proxy_returns_502_on_connection_error(aiohttp_client, tmp_path):
    """Proxy returns 502 when upstream is unreachable."""
    # Point proxy at a port nothing is listening on
    proxy_app = create_app(target="http://127.0.0.1:1")

    with patch("luna_monitor.proxy.server._RATE_LIMIT_FILE", str(tmp_path / "rl.jsonl")), \
         patch("luna_monitor.proxy.server._RATE_LIMIT_DIR", str(tmp_path)):
        client = await aiohttp_client(proxy_app)
        resp = await client.post("/v1/messages", json={"test": True})

    assert resp.status == 502
    body = await resp.text()
    assert "Proxy error" in body
