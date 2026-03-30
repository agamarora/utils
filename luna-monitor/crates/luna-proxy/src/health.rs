use bytes::Bytes;
use http_body_util::Full;
use hyper::{Request, Response, body::Incoming};
use luna_common::types::ProxyHealth;
use std::sync::Arc;
use crate::proxy::ProxyState;

pub async fn handle(
    _req: Request<Incoming>,
    state: Arc<ProxyState>,
) -> Result<Response<Full<Bytes>>, hyper::Error> {
    let health = ProxyHealth {
        status: "ok".to_string(),
        uptime_s: state.start_time.elapsed().as_secs(),
        requests_proxied: state.requests_proxied.load(std::sync::atomic::Ordering::Relaxed),
        last_capture_ts: state.last_capture_ts.lock().unwrap().clone(),
        api_errors_total: state.errors_total.load(std::sync::atomic::Ordering::Relaxed),
        api_errors_429: state.errors_429.load(std::sync::atomic::Ordering::Relaxed),
        last_latency_ms: {
            let ms = *state.last_latency_ms.lock().unwrap();
            (ms * 10.0).round() / 10.0
        },
    };
    let body = serde_json::to_string(&health).unwrap();
    Ok(Response::builder()
        .status(200)
        .header("content-type", "application/json")
        .body(Full::new(Bytes::from(body)))
        .unwrap())
}
