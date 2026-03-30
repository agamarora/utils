use serde::{Deserialize, Serialize};

/// Rate limit entry written by luna-proxy, read by luna-monitor.
/// One per line in ~/.luna-monitor/rate-limits.jsonl
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitEntry {
    #[serde(rename = "5h_utilization", skip_serializing_if = "Option::is_none")]
    pub five_h_utilization: Option<f64>,
    #[serde(rename = "7d_utilization", skip_serializing_if = "Option::is_none")]
    pub seven_d_utilization: Option<f64>,
    #[serde(rename = "5h_reset", skip_serializing_if = "Option::is_none")]
    pub five_h_reset: Option<String>,
    #[serde(rename = "7d_reset", skip_serializing_if = "Option::is_none")]
    pub seven_d_reset: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    pub ts: String,
}

/// Health response from GET /health
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProxyHealth {
    pub status: String,
    pub uptime_s: u64,
    pub requests_proxied: u64,
    pub last_capture_ts: String,
    pub api_errors_total: u64,
    pub api_errors_429: u64,
    pub last_latency_ms: f64,
}

/// Usage window from Anthropic API
#[derive(Debug, Clone, Default)]
pub struct UsageWindow {
    pub utilization: f64,
    pub resets_at: String,
}

/// All usage data from Anthropic API or proxy
#[derive(Debug, Clone, Default)]
pub struct UsageData {
    pub five_hour: UsageWindow,
    pub seven_day: UsageWindow,
    pub seven_day_opus: UsageWindow,
    pub seven_day_sonnet: UsageWindow,
    pub plan_name: String,
    pub error: Option<String>,
    pub fetched_at: Option<f64>,
    pub source: String,
}

/// Local JSONL usage data from ~/.claude/projects/**/*.jsonl
#[derive(Debug, Clone, Default)]
pub struct LocalUsageData {
    pub tokens_5h: u64,
    pub tokens_7d: u64,
    pub requests_5h: u64,
    pub burn_rate: f64,
    pub model_breakdown: Vec<(String, u64)>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rate_limit_entry_serialize_roundtrip() {
        let entry = RateLimitEntry {
            five_h_utilization: Some(0.42),
            seven_d_utilization: Some(0.18),
            five_h_reset: Some("1774796400".to_string()),
            seven_d_reset: None,
            status: Some("allowed".to_string()),
            ts: "2026-03-30T12:00:00Z".to_string(),
        };
        let json = serde_json::to_string(&entry).unwrap();
        let parsed: RateLimitEntry = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.five_h_utilization, Some(0.42));
        assert_eq!(parsed.seven_d_utilization, Some(0.18));
        assert!(parsed.seven_d_reset.is_none());
    }

    #[test]
    fn test_rate_limit_entry_skip_none_fields() {
        let entry = RateLimitEntry {
            five_h_utilization: Some(0.5),
            seven_d_utilization: None,
            five_h_reset: None,
            seven_d_reset: None,
            status: None,
            ts: "2026-03-30T12:00:00Z".to_string(),
        };
        let json = serde_json::to_string(&entry).unwrap();
        assert!(!json.contains("7d_utilization"));
        assert!(!json.contains("status"));
    }

    #[test]
    fn test_proxy_health_serialize() {
        let health = ProxyHealth {
            status: "ok".to_string(),
            uptime_s: 123,
            requests_proxied: 42,
            last_capture_ts: "2026-03-30T12:00:00Z".to_string(),
            api_errors_total: 2,
            api_errors_429: 1,
            last_latency_ms: 234.5,
        };
        let json = serde_json::to_string(&health).unwrap();
        let parsed: ProxyHealth = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.requests_proxied, 42);
        assert_eq!(parsed.last_latency_ms, 234.5);
    }
}
