use luna_common::paths;
use luna_common::types::{ProxyHealth, RateLimitEntry};
use std::time::Instant;

pub struct RateLimitCollector {
    last_read: Instant,
    cached: Option<RateLimitEntry>,
}

impl RateLimitCollector {
    pub fn new() -> Self {
        Self {
            last_read: Instant::now() - std::time::Duration::from_secs(10),
            cached: None,
        }
    }

    pub fn collect(&mut self) -> Option<RateLimitEntry> {
        if self.last_read.elapsed() < std::time::Duration::from_secs(2) {
            return self.cached.clone();
        }
        self.last_read = Instant::now();

        let path = paths::rate_limit_file()?;
        let content = std::fs::read_to_string(&path).ok()?;

        // Read last non-empty line
        let last_line = content.lines().rev().find(|l| !l.trim().is_empty())?;
        let entry: RateLimitEntry = serde_json::from_str(last_line).ok()?;
        self.cached = Some(entry.clone());
        Some(entry)
    }

    pub fn is_fresh(&self) -> bool {
        if let Some(ref entry) = self.cached {
            if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(&entry.ts) {
                let now = chrono::Utc::now();
                let age = now.signed_duration_since(dt);
                return age.num_seconds() < 60;
            }
            // Try parsing as custom format
            if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(&entry.ts, "%Y-%m-%dT%H:%M:%SZ") {
                let now = chrono::Utc::now().naive_utc();
                let age = now.signed_duration_since(dt);
                return age.num_seconds() < 60;
            }
        }
        false
    }

    pub fn proxy_health(port: u16) -> Option<ProxyHealth> {
        let url = format!("http://127.0.0.1:{}/health", port);
        // Synchronous HTTP — use a short timeout
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(1))
            .build()
            .ok()?;
        let resp = client.get(&url).send().ok()?;
        let health: ProxyHealth = resp.json().ok()?;
        Some(health)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_read_last_line() {
        let tmp = std::env::temp_dir().join("luna-test-rl.jsonl");
        let lines = vec![
            r#"{"5h_utilization":0.1,"ts":"2026-03-30T10:00:00Z"}"#,
            r#"{"5h_utilization":0.2,"ts":"2026-03-30T11:00:00Z"}"#,
            r#"{"5h_utilization":0.3,"ts":"2026-03-30T12:00:00Z"}"#,
        ];
        std::fs::write(&tmp, lines.join("\n")).unwrap();

        let content = std::fs::read_to_string(&tmp).unwrap();
        let last_line = content.lines().rev().find(|l| !l.trim().is_empty()).unwrap();
        let entry: RateLimitEntry = serde_json::from_str(last_line).unwrap();
        assert_eq!(entry.five_h_utilization, Some(0.3));

        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn test_freshness_within_60s() {
        let ts = chrono::Utc::now() - chrono::Duration::seconds(30);
        let entry = RateLimitEntry {
            five_h_utilization: Some(0.5),
            seven_d_utilization: None,
            five_h_reset: None,
            seven_d_reset: None,
            status: None,
            ts: ts.format("%Y-%m-%dT%H:%M:%SZ").to_string(),
        };
        let collector = RateLimitCollector {
            last_read: Instant::now(),
            cached: Some(entry),
        };
        assert!(collector.is_fresh());
    }

    #[test]
    fn test_freshness_stale() {
        let ts = chrono::Utc::now() - chrono::Duration::seconds(120);
        let entry = RateLimitEntry {
            five_h_utilization: Some(0.5),
            seven_d_utilization: None,
            five_h_reset: None,
            seven_d_reset: None,
            status: None,
            ts: ts.format("%Y-%m-%dT%H:%M:%SZ").to_string(),
        };
        let collector = RateLimitCollector {
            last_read: Instant::now(),
            cached: Some(entry),
        };
        assert!(!collector.is_fresh());
    }

    #[test]
    fn test_proxy_health_unreachable() {
        // No proxy on port 19999
        let health = RateLimitCollector::proxy_health(19999);
        assert!(health.is_none());
    }
}
