use serde::{Deserialize, Serialize};

/// A single entry from the proxy's rate-limits.jsonl
/// Includes both header-based fields (existing) and body-based fields (new in luna-tt)
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RateLimitEntry {
    // From response headers (same as luna-monitor)
    #[serde(rename = "5h_utilization")]
    pub five_h_utilization: Option<f64>,
    #[serde(rename = "7d_utilization")]
    pub seven_d_utilization: Option<f64>,
    #[serde(rename = "5h_reset")]
    pub five_h_reset: Option<String>,
    #[serde(rename = "7d_reset")]
    pub seven_d_reset: Option<String>,
    pub status: Option<String>,
    pub ts: String,

    // From response body (new in luna-tt)
    pub model: Option<String>,
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    pub cache_read_tokens: Option<u64>,
    pub stop_reason: Option<String>,
}

/// Health check response from the proxy's /health endpoint
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

/// Merged usage data for the Claude Status panel
#[derive(Debug, Clone, Default)]
pub struct UsageData {
    pub five_hour_utilization: f64,
    pub seven_day_utilization: f64,
    pub five_hour_reset: String,
    pub seven_day_reset: String,
    pub source: String, // "proxy" or "none"
    pub status: String, // "allowed", "rate_limited", etc.
}

/// System metrics, ALL normalized to 0.0-1.0
#[derive(Debug, Clone, Default)]
pub struct SystemMorphs {
    pub cpu: f64,           // aggregate CPU %  / 100
    pub ram: f64,           // used_ram / total_ram
    pub disk_active: f64,   // weighted avg of all disk active % / 100
    pub net_bytes_sec: f64, // normalized: min(1.0, bytes/sec / 10_000_000)
}

/// A proxy event, derived from a JSONL entry, used to feed the growth engine
#[derive(Debug, Clone)]
pub struct ProxyEvent {
    pub model_hash: f64,       // hash(model_string) normalized to 0.0-1.0
    pub input_tokens: f64,     // normalized 0.0-1.0
    pub output_tokens: f64,    // normalized 0.0-1.0
    pub cache_ratio: f64,      // cache_read / max(input, 1), 0.0-1.0
    pub stop_reason: StopKind,
    pub is_rate_limited: bool,
    pub five_h_utilization: f64,
    pub seven_d_utilization: f64,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum StopKind {
    EndTurn,
    ToolUse,
    MaxTokens,
    Other,
}

impl ProxyEvent {
    /// Create from a raw JSONL entry, normalizing all fields to 0.0-1.0
    pub fn from_entry(entry: &RateLimitEntry) -> Self {
        let model_hash = entry.model.as_deref()
            .map(hash_string_to_unit)
            .unwrap_or(0.5);

        let input_tokens = entry.input_tokens
            .map(|t| (t as f64 / 50_000.0).min(1.0))
            .unwrap_or(0.0);

        let output_tokens = entry.output_tokens
            .map(|t| (t as f64 / 10_000.0).min(1.0))
            .unwrap_or(0.0);

        let cache_read = entry.cache_read_tokens.unwrap_or(0) as f64;
        let input_raw = entry.input_tokens.unwrap_or(1).max(1) as f64;
        let cache_ratio = (cache_read / input_raw).min(1.0);

        let stop_reason = match entry.stop_reason.as_deref() {
            Some("tool_use") => StopKind::ToolUse,
            Some("max_tokens") => StopKind::MaxTokens,
            Some("end_turn") => StopKind::EndTurn,
            _ => StopKind::Other,
        };

        let is_rate_limited = entry.status.as_deref() == Some("rate_limited");

        let five_h = entry.five_h_utilization
            .map(|v| if v > 1.0 { v / 100.0 } else { v })
            .unwrap_or(0.0);
        let seven_d = entry.seven_d_utilization
            .map(|v| if v > 1.0 { v / 100.0 } else { v })
            .unwrap_or(0.0);

        ProxyEvent {
            model_hash,
            input_tokens,
            output_tokens,
            cache_ratio,
            stop_reason,
            is_rate_limited,
            five_h_utilization: five_h,
            seven_d_utilization: seven_d,
        }
    }
}

/// Hash a string to a value in [0.0, 1.0) using a simple but well-distributed hash
/// Uses FNV-1a with additional bit mixing for uniform distribution
pub fn hash_string_to_unit(s: &str) -> f64 {
    let mut h: u64 = 0xcbf29ce484222325; // FNV offset basis
    for byte in s.bytes() {
        h ^= byte as u64;
        h = h.wrapping_mul(0x100000001b3); // FNV prime
    }
    // Additional bit mixing (splitmix64 finalizer) for better distribution
    h ^= h >> 30;
    h = h.wrapping_mul(0xbf58476d1ce4e5b9);
    h ^= h >> 27;
    h = h.wrapping_mul(0x94d049bb133111eb);
    h ^= h >> 31;
    // Normalize to [0.0, 1.0)
    (h as f64) / (u64::MAX as f64)
}

/// Info returned by export/import operations
pub struct GrowthInfo {
    pub total_particles: u32,
    pub age_days: u32,
    pub created_at: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hash_string_to_unit_range() {
        for model in &["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"] {
            let h = hash_string_to_unit(model);
            assert!(h >= 0.0 && h < 1.0, "hash({}) = {} out of range", model, h);
        }
    }

    #[test]
    fn test_hash_string_deterministic() {
        assert_eq!(
            hash_string_to_unit("claude-opus-4-6"),
            hash_string_to_unit("claude-opus-4-6")
        );
    }

    #[test]
    fn test_hash_different_models_differ() {
        let h1 = hash_string_to_unit("claude-opus-4-6");
        let h2 = hash_string_to_unit("claude-sonnet-4-6");
        let h3 = hash_string_to_unit("claude-haiku-4-5");
        assert!((h1 - h2).abs() > 0.001, "opus and sonnet too similar");
        assert!((h2 - h3).abs() > 0.001, "sonnet and haiku too similar");
    }

    #[test]
    fn test_proxy_event_normalization() {
        let entry = RateLimitEntry {
            five_h_utilization: Some(42.0), // percentage form
            seven_d_utilization: Some(0.18), // fraction form
            model: Some("claude-opus-4-6".to_string()),
            input_tokens: Some(5000),
            output_tokens: Some(2000),
            cache_read_tokens: Some(3000),
            stop_reason: Some("tool_use".to_string()),
            status: Some("allowed".to_string()),
            ts: "2026-03-30T12:00:00Z".to_string(),
            ..Default::default()
        };

        let event = ProxyEvent::from_entry(&entry);
        assert!((event.five_h_utilization - 0.42).abs() < 0.01);
        assert!((event.seven_d_utilization - 0.18).abs() < 0.01);
        assert!((event.input_tokens - 0.1).abs() < 0.01); // 5000/50000
        assert!((event.output_tokens - 0.2).abs() < 0.01); // 2000/10000
        assert!((event.cache_ratio - 0.6).abs() < 0.01); // 3000/5000
        assert_eq!(event.stop_reason, StopKind::ToolUse);
        assert!(!event.is_rate_limited);
    }
}
