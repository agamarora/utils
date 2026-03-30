use bytes::Bytes;
use http_body_util::{BodyExt, Full};
use hyper::body::Incoming;
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request, Response, StatusCode, Uri};
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioExecutor;
use hyper_util::rt::TokioIo;
use crate::types::RateLimitEntry;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;
use tokio::net::TcpListener;

use super::jsonl;
use super::sse::SseAccumulator;

/// Headers to capture from upstream responses
const CAPTURE_HEADERS: &[(&str, &str)] = &[
    ("anthropic-ratelimit-unified-5h-utilization", "5h_utilization"),
    ("anthropic-ratelimit-unified-7d-utilization", "7d_utilization"),
    ("anthropic-ratelimit-unified-5h-reset", "5h_reset"),
    ("anthropic-ratelimit-unified-7d-reset", "7d_reset"),
    ("anthropic-ratelimit-unified-status", "status"),
];

/// Hop-by-hop headers to strip from forwarded responses
const HOP_BY_HOP: &[&str] = &[
    "transfer-encoding",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "upgrade",
];

pub struct ProxyState {
    pub target: String,
    pub client: Client<hyper_tls::HttpsConnector<hyper_util::client::legacy::connect::HttpConnector>, Full<Bytes>>,
    pub start_time: Instant,
    pub requests_proxied: AtomicU64,
    pub errors_total: AtomicU64,
    pub errors_429: AtomicU64,
    pub last_latency_ms: Mutex<f64>,
    pub last_capture_ts: Mutex<String>,
    pub jsonl_path: std::path::PathBuf,
}

impl ProxyState {
    pub fn new(target: String, jsonl_path: std::path::PathBuf) -> Self {
        let https = hyper_tls::HttpsConnector::new();
        let client = Client::builder(TokioExecutor::new())
            .build(https);

        Self {
            target,
            client,
            start_time: Instant::now(),
            requests_proxied: AtomicU64::new(0),
            errors_total: AtomicU64::new(0),
            errors_429: AtomicU64::new(0),
            last_latency_ms: Mutex::new(0.0),
            last_capture_ts: Mutex::new(String::new()),
            jsonl_path,
        }
    }
}

async fn handle(
    req: Request<Incoming>,
    state: Arc<ProxyState>,
) -> Result<Response<Full<Bytes>>, hyper::Error> {
    // Health endpoint
    let path = req.uri().path();
    if path == "/health" || path == "/health/" {
        return super::health::handle(req, state).await;
    }

    let req_start = Instant::now();
    state.requests_proxied.fetch_add(1, Ordering::Relaxed);

    // Build target URL
    let path_and_query = req.uri().path_and_query()
        .map(|pq| pq.as_str())
        .unwrap_or("/");
    let target_url = format!("{}{}", state.target, path_and_query);
    let target_uri: Uri = match target_url.parse() {
        Ok(uri) => uri,
        Err(e) => {
            return Ok(error_response(502, format!("Invalid target URL: {}", e)));
        }
    };

    // Collect incoming request body
    let method = req.method().clone();
    let req_headers = req.headers().clone();
    let body_bytes = match req.collect().await {
        Ok(collected) => collected.to_bytes(),
        Err(e) => {
            return Ok(error_response(502, format!("Failed to read request body: {}", e)));
        }
    };

    // Build upstream request
    let mut upstream_req = Request::builder()
        .method(method)
        .uri(target_uri);

    for (name, value) in req_headers.iter() {
        if name.as_str().eq_ignore_ascii_case("host") {
            continue;
        }
        upstream_req = upstream_req.header(name, value);
    }

    let upstream_req = match upstream_req.body(Full::new(body_bytes)) {
        Ok(req) => req,
        Err(e) => {
            return Ok(error_response(502, format!("Failed to build upstream request: {}", e)));
        }
    };

    // Forward to upstream
    let upstream_resp = match tokio::time::timeout(
        std::time::Duration::from_secs(300),
        state.client.request(upstream_req),
    ).await {
        Ok(Ok(resp)) => resp,
        Ok(Err(e)) => {
            state.errors_total.fetch_add(1, Ordering::Relaxed);
            return Ok(error_response(502, format!("Proxy error: {}", e)));
        }
        Err(_) => {
            state.errors_total.fetch_add(1, Ordering::Relaxed);
            return Ok(error_response(504, "Upstream timeout".to_string()));
        }
    };

    // Record latency
    let latency_ms = req_start.elapsed().as_secs_f64() * 1000.0;
    *state.last_latency_ms.lock().unwrap() = latency_ms;

    // Track errors
    let status = upstream_resp.status();
    if status.as_u16() >= 400 {
        state.errors_total.fetch_add(1, Ordering::Relaxed);
    }
    if status == StatusCode::TOO_MANY_REQUESTS {
        state.errors_429.fetch_add(1, Ordering::Relaxed);
    }

    // Capture rate limit headers
    let mut entry = capture_headers(upstream_resp.headers());

    // Check if SSE response
    let is_sse = upstream_resp.headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .map(|ct| ct.contains("text/event-stream"))
        .unwrap_or(false);

    // Build response headers (strip hop-by-hop)
    let resp_status = upstream_resp.status();
    let mut response_builder = Response::builder().status(resp_status);
    for (name, value) in upstream_resp.headers().iter() {
        let name_lower = name.as_str().to_lowercase();
        if HOP_BY_HOP.contains(&name_lower.as_str()) {
            continue;
        }
        response_builder = response_builder.header(name, value);
    }

    // Read full body (we buffer either way since we need Full<Bytes> for response)
    // For SSE, we parse the body for fields while buffering
    let body_bytes = match upstream_resp.collect().await {
        Ok(collected) => collected.to_bytes(),
        Err(e) => {
            return Ok(error_response(502, format!("Failed to read upstream response: {}", e)));
        }
    };

    if is_sse {
        // Parse SSE events from the buffered body
        let mut acc = SseAccumulator::new();
        let body_str = String::from_utf8_lossy(&body_bytes);
        for line in body_str.lines() {
            acc.feed_line(line);
        }
        let (model, input_tokens, output_tokens, cache_read_tokens, stop_reason) = acc.finish();

        // Merge body fields into the entry
        if let Some(ref mut e) = entry {
            e.model = model;
            e.input_tokens = input_tokens;
            e.output_tokens = output_tokens;
            e.cache_read_tokens = cache_read_tokens;
            e.stop_reason = stop_reason;
        } else if model.is_some() || input_tokens.is_some() {
            // No headers but we got body data — create a minimal entry
            entry = Some(RateLimitEntry {
                ts: chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string(),
                model,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                stop_reason,
                ..Default::default()
            });
        }
    } else {
        // Non-SSE: try to parse JSON body for usage data
        if let Ok(json) = serde_json::from_slice::<serde_json::Value>(&body_bytes) {
            let model = json.get("model").and_then(|v| v.as_str()).map(|s| s.to_string());
            let input_tokens = json.get("usage")
                .and_then(|u| u.get("input_tokens"))
                .and_then(|v| v.as_u64());
            let output_tokens = json.get("usage")
                .and_then(|u| u.get("output_tokens"))
                .and_then(|v| v.as_u64());
            let cache_read_tokens = json.get("usage")
                .and_then(|u| u.get("cache_read_input_tokens"))
                .and_then(|v| v.as_u64());
            let stop_reason = json.get("stop_reason")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            if let Some(ref mut e) = entry {
                e.model = model;
                e.input_tokens = input_tokens;
                e.output_tokens = output_tokens;
                e.cache_read_tokens = cache_read_tokens;
                e.stop_reason = stop_reason;
            } else if model.is_some() {
                entry = Some(RateLimitEntry {
                    ts: chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string(),
                    model,
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    stop_reason,
                    ..Default::default()
                });
            }
        }
    }

    // Write JSONL entry if we captured anything
    if let Some(e) = entry {
        *state.last_capture_ts.lock().unwrap() = e.ts.clone();
        let path = state.jsonl_path.clone();
        tokio::spawn(async move {
            jsonl::write_entry(&path, &e);
        });
    }

    Ok(response_builder.body(Full::new(body_bytes)).unwrap())
}

fn capture_headers(headers: &hyper::HeaderMap) -> Option<RateLimitEntry> {
    let mut has_any = false;
    let mut five_h_util = None;
    let mut seven_d_util = None;
    let mut five_h_reset = None;
    let mut seven_d_reset = None;
    let mut status_val = None;

    for (header_name, short_key) in CAPTURE_HEADERS {
        if let Some(val) = headers.get(*header_name) {
            has_any = true;
            let val_str = val.to_str().unwrap_or("").to_string();
            match *short_key {
                "5h_utilization" => five_h_util = val_str.parse::<f64>().ok(),
                "7d_utilization" => seven_d_util = val_str.parse::<f64>().ok(),
                "5h_reset" => five_h_reset = Some(val_str),
                "7d_reset" => seven_d_reset = Some(val_str),
                "status" => status_val = Some(val_str),
                _ => {}
            }
        }
    }

    if !has_any {
        return None;
    }

    let ts = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string();

    Some(RateLimitEntry {
        five_h_utilization: five_h_util,
        seven_d_utilization: seven_d_util,
        five_h_reset,
        seven_d_reset,
        status: status_val,
        ts,
        model: None,
        input_tokens: None,
        output_tokens: None,
        cache_read_tokens: None,
        stop_reason: None,
    })
}

fn error_response(status: u16, message: String) -> Response<Full<Bytes>> {
    Response::builder()
        .status(status)
        .body(Full::new(Bytes::from(message)))
        .unwrap()
}

/// Start the proxy server on the given port.
pub async fn run(port: u16) {
    let jsonl_path = crate::paths::rate_limit_file()
        .unwrap_or_else(|| std::path::PathBuf::from("rate-limits.jsonl"));

    // Rotate JSONL on startup
    jsonl::rotate(&jsonl_path, 10000);

    let state = Arc::new(ProxyState::new(
        "https://api.anthropic.com".to_string(),
        jsonl_path,
    ));

    // Write PID file
    if let Some(pid_path) = crate::paths::proxy_pid_file() {
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        let _ = std::fs::write(&pid_path, format!("{} {}", std::process::id(), ts));
    }

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let listener = match TcpListener::bind(addr).await {
        Ok(l) => l,
        Err(e) => {
            eprintln!("Failed to bind proxy to {}: {}", addr, e);
            return;
        }
    };

    tracing::info!("luna-tt proxy listening on {}", addr);

    loop {
        let (stream, _) = match listener.accept().await {
            Ok(s) => s,
            Err(_) => continue,
        };
        let state = state.clone();
        tokio::spawn(async move {
            let io = TokioIo::new(stream);
            let service = service_fn(move |req| {
                let state = state.clone();
                async move { handle(req, state).await }
            });
            let _ = http1::Builder::new()
                .serve_connection(io, service)
                .await;
        });
    }
}
