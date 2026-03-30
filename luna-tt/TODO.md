# luna-tt — TODO

> Built on luna-monitor's embedded proxy. All data below already flows through `localhost:9120` — we just need to capture it.

## Untapped data from the proxy

### Response headers — rate limit bucket state (15 headers, not captured)

| Header | Value |
|---|---|
| `anthropic-ratelimit-requests-limit` | Max requests per minute |
| `anthropic-ratelimit-requests-remaining` | Requests left this window |
| `anthropic-ratelimit-requests-reset` | When request limit replenishes (RFC 3339) |
| `anthropic-ratelimit-tokens-limit` | Max tokens/min (most restrictive active limit) |
| `anthropic-ratelimit-tokens-remaining` | Tokens left (rounded to nearest 1000) |
| `anthropic-ratelimit-tokens-reset` | When token limit replenishes (RFC 3339) |
| `anthropic-ratelimit-input-tokens-limit` | Max input tokens/min |
| `anthropic-ratelimit-input-tokens-remaining` | Input tokens left |
| `anthropic-ratelimit-input-tokens-reset` | Input token reset time (RFC 3339) |
| `anthropic-ratelimit-output-tokens-limit` | Max output tokens/min |
| `anthropic-ratelimit-output-tokens-remaining` | Output tokens left |
| `anthropic-ratelimit-output-tokens-reset` | Output token reset time (RFC 3339) |
| `retry-after` | Seconds to wait (only on 429) |
| `request-id` | Unique request ID for correlation |
| `x-should-retry` | Whether client should retry |

### Response body — per-request metrics (not inspected today)

| Field | Value |
|---|---|
| `id` | Message ID (e.g. `msg_01XFD...`) |
| `model` | Actual model used (e.g. `claude-opus-4-6`, `claude-sonnet-4-6`) |
| `stop_reason` | `end_turn`, `max_tokens`, `tool_use`, `stop_sequence` |
| `usage.input_tokens` | Input tokens (after last cache breakpoint) |
| `usage.output_tokens` | Output tokens generated |
| `usage.cache_creation_input_tokens` | Tokens written to cache |
| `usage.cache_read_input_tokens` | Tokens read from cache (free) |
| `content[].type` | Content block types: `text`, `tool_use`, `thinking` |

### Response headers — infra (low priority)

| Header | Value |
|---|---|
| `x-envoy-upstream-service-time` | Upstream latency in ms |
| `server-timing` | Origin response duration |
| `cf-ray` | Cloudflare ray ID |

## What we already capture (for reference)

| Header | Stored as |
|---|---|
| `anthropic-ratelimit-unified-5h-utilization` | 5h usage fraction (0-1) |
| `anthropic-ratelimit-unified-7d-utilization` | 7d usage fraction (0-1) |
| `anthropic-ratelimit-unified-5h-reset` | 5h window reset (unix epoch) |
| `anthropic-ratelimit-unified-7d-reset` | 7d window reset (unix epoch) |
| `anthropic-ratelimit-unified-status` | `allowed` / rate limit status |

## Ideas — what could we build with this

- [ ] Per-session token accounting (input + output + cache, cost estimate)
- [ ] Model usage breakdown (opus vs sonnet vs haiku split)
- [ ] Token bucket visualizer (remaining capacity, replenishment rate)
- [ ] Request log with latency, model, tokens, stop reason
- [ ] Cache hit rate tracking (cache_read vs total input)
- [ ] Cost estimator (tokens x model pricing)
- [ ] Alert when approaching RPM/TPM limits
- [ ] Conversation analytics (avg tokens per turn, tool use frequency)
