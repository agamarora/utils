use crate::types::RateLimitEntry;
use std::path::PathBuf;
use std::time::Instant;

/// Reads the last line of the rate-limits.jsonl file, with a 2-second cache.
pub struct RateLimitCollector {
    path: PathBuf,
    cached: Option<RateLimitEntry>,
    last_read: Instant,
    cache_ttl_secs: f64,
}

impl RateLimitCollector {
    pub fn new(path: PathBuf) -> Self {
        Self {
            path,
            cached: None,
            last_read: Instant::now() - std::time::Duration::from_secs(10), // force first read
            cache_ttl_secs: 2.0,
        }
    }

    /// Read the latest entry, using cache if fresh enough.
    pub fn latest(&mut self) -> Option<&RateLimitEntry> {
        if self.last_read.elapsed().as_secs_f64() >= self.cache_ttl_secs {
            self.cached = read_last_line(&self.path);
            self.last_read = Instant::now();
        }
        self.cached.as_ref()
    }

    /// Check if the cached entry is recent (timestamp < 60s old).
    pub fn is_fresh(&self) -> bool {
        match &self.cached {
            Some(entry) => {
                if let Ok(ts) = chrono::DateTime::parse_from_rfc3339(&entry.ts) {
                    let age = chrono::Utc::now().signed_duration_since(ts);
                    age.num_seconds() < 60
                } else {
                    // Try parsing as a simpler format (e.g. "2026-03-30T12:00:00Z")
                    if let Ok(ts) = chrono::NaiveDateTime::parse_from_str(&entry.ts, "%Y-%m-%dT%H:%M:%SZ") {
                        let now = chrono::Utc::now().naive_utc();
                        let age = now.signed_duration_since(ts);
                        age.num_seconds() < 60
                    } else {
                        false
                    }
                }
            }
            None => false,
        }
    }
}

/// Read the last line of a JSONL file and parse it.
fn read_last_line(path: &PathBuf) -> Option<RateLimitEntry> {
    let content = std::fs::read_to_string(path).ok()?;
    let last_line = content.lines().rev().find(|l| !l.trim().is_empty())?;
    serde_json::from_str(last_line).ok()
}
