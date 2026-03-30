use bytes::Bytes;
use http_body_util::{BodyExt, Full};
use hyper::body::Incoming;
use hyper::{Request, Response, StatusCode, Uri};
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioExecutor;
use luna_common::types::RateLimitEntry;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use super::jsonl;

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

pub async fn handle(
    req: Request<Incoming>,
    state: Arc<ProxyState>,
) -> Result<Response<Full<Bytes>>, hyper::Error> {
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
            return Ok(error_response(502, format!("Proxy error: {}", e)));
        }
        Err(_) => {
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
    if let Some(entry) = capture_headers(upstream_resp.headers()) {
        *state.last_capture_ts.lock().unwrap() = entry.ts.clone();
        let path = state.jsonl_path.clone();
        tokio::spawn(async move {
            jsonl::write_entry(&path, &entry);
        });
    }

    // Build response
    let mut response = Response::builder().status(status);
    for (name, value) in upstream_resp.headers().iter() {
        let name_lower = name.as_str().to_lowercase();
        if HOP_BY_HOP.contains(&name_lower.as_str()) {
            continue;
        }
        response = response.header(name, value);
    }

    let body_bytes = match upstream_resp.collect().await {
        Ok(collected) => collected.to_bytes(),
        Err(e) => {
            return Ok(error_response(502, format!("Failed to read upstream response: {}", e)));
        }
    };

    Ok(response.body(Full::new(body_bytes)).unwrap())
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
    })
}

fn error_response(status: u16, message: String) -> Response<Full<Bytes>> {
    Response::builder()
        .status(status)
        .body(Full::new(Bytes::from(message)))
        .unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;
    use hyper::HeaderMap;

    #[test]
    fn test_capture_all_five_headers() {
        let mut headers = HeaderMap::new();
        headers.insert("anthropic-ratelimit-unified-5h-utilization", "0.42".parse().unwrap());
        headers.insert("anthropic-ratelimit-unified-7d-utilization", "0.18".parse().unwrap());
        headers.insert("anthropic-ratelimit-unified-5h-reset", "1774796400".parse().unwrap());
        headers.insert("anthropic-ratelimit-unified-7d-reset", "1775400000".parse().unwrap());
        headers.insert("anthropic-ratelimit-unified-status", "allowed".parse().unwrap());

        let entry = capture_headers(&headers).unwrap();
        assert_eq!(entry.five_h_utilization, Some(0.42));
        assert_eq!(entry.seven_d_utilization, Some(0.18));
        assert_eq!(entry.five_h_reset.as_deref(), Some("1774796400"));
        assert_eq!(entry.seven_d_reset.as_deref(), Some("1775400000"));
        assert_eq!(entry.status.as_deref(), Some("allowed"));
    }

    #[test]
    fn test_capture_no_headers() {
        let headers = HeaderMap::new();
        assert!(capture_headers(&headers).is_none());
    }
}
