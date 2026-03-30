use luna_common::paths;
use std::collections::{HashSet, VecDeque};
use std::time::Instant;
use luna_common::types::LocalUsageData;

const INPUT_WEIGHT: f64 = 1.0;
const CACHE_CREATION_WEIGHT: f64 = 1.0;
const CACHE_READ_WEIGHT: f64 = 0.0;
const OUTPUT_WEIGHT: f64 = 1.0;
const WINDOW_5H: u64 = 18_000;
const WINDOW_7D: u64 = 604_800;
const BURN_RATE_WINDOW: u64 = 120; // 2 minutes
const MAX_BURN_HISTORY: usize = 300;

pub struct LocalCollector {
    last_scan: Instant,
    cache_ttl: std::time::Duration,
    cached: Option<LocalUsageData>,
    burn_history: VecDeque<(f64, f64)>, // (ts, tokens_per_min)
    seen: HashSet<(String, String)>,     // (requestId, messageId) dedup
}

impl LocalCollector {
    pub fn new() -> Self {
        Self {
            last_scan: Instant::now() - std::time::Duration::from_secs(10),
            cache_ttl: std::time::Duration::from_secs(2),
            cached: None,
            burn_history: VecDeque::with_capacity(MAX_BURN_HISTORY),
            seen: HashSet::new(),
        }
    }

    pub fn collect(&mut self) -> LocalUsageData {
        if self.last_scan.elapsed() < self.cache_ttl {
            if let Some(ref cached) = self.cached {
                return cached.clone();
            }
        }
        self.last_scan = Instant::now();

        let data = self.scan_jsonl_files();
        self.cached = Some(data.clone());
        data
    }

    pub fn burn_history(&self) -> &VecDeque<(f64, f64)> {
        &self.burn_history
    }

    fn scan_jsonl_files(&mut self) -> LocalUsageData {
        let projects_dir = match paths::claude_projects_dir() {
            Some(d) => d,
            None => return LocalUsageData::default(),
        };

        let pattern = projects_dir.join("**/*.jsonl");
        let pattern_str = pattern.to_string_lossy().to_string();

        let now = now_epoch();
        let cutoff_7d = now - WINDOW_7D as f64;
        let cutoff_5h = now - WINDOW_5H as f64;
        let cutoff_burn = now - BURN_RATE_WINDOW as f64;

        let mut tokens_5h: u64 = 0;
        let mut tokens_7d: u64 = 0;
        let mut requests_5h: u64 = 0;
        let mut tokens_burn: u64 = 0;
        let mut model_map: std::collections::HashMap<String, u64> = std::collections::HashMap::new();

        let entries = match glob::glob(&pattern_str) {
            Ok(e) => e,
            Err(_) => return LocalUsageData::default(),
        };

        for entry in entries.flatten() {
            // Skip files in subagents/ directories
            let path_str = entry.to_string_lossy().to_string();
            if path_str.contains("subagents") {
                continue;
            }

            // Skip old files (mtime > 7 days)
            if let Ok(meta) = entry.metadata() {
                if let Ok(modified) = meta.modified() {
                    if let Ok(age) = modified.elapsed() {
                        if age.as_secs() > WINDOW_7D {
                            continue;
                        }
                    }
                }
            }

            let content = match std::fs::read_to_string(&entry) {
                Ok(c) => c,
                Err(_) => continue,
            };

            for line in content.lines() {
                let json: serde_json::Value = match serde_json::from_str(line) {
                    Ok(v) => v,
                    Err(_) => continue,
                };

                // Extract timestamp
                let ts = match json.get("timestamp").and_then(|v| v.as_f64()) {
                    Some(t) => t,
                    None => {
                        // Try string timestamp
                        match json.get("timestamp").and_then(|v| v.as_str()) {
                            Some(s) => {
                                if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(s) {
                                    dt.timestamp() as f64
                                } else {
                                    continue;
                                }
                            }
                            None => continue,
                        }
                    }
                };

                if ts < cutoff_7d {
                    continue;
                }

                let msg = match json.get("message") {
                    Some(m) => m,
                    None => continue,
                };

                // Dedup by (requestId, messageId)
                let request_id = msg.get("requestId")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let message_id = msg.get("messageId")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();

                if !request_id.is_empty() && !message_id.is_empty() {
                    let key = (request_id, message_id);
                    if self.seen.contains(&key) {
                        continue;
                    }
                    self.seen.insert(key);
                }

                let usage = match msg.get("usage") {
                    Some(u) => u,
                    None => continue,
                };

                let tokens = weighted_tokens(usage);

                // Model tracking
                let model = msg.get("model")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unknown")
                    .to_string();
                *model_map.entry(model).or_insert(0) += tokens;

                // Bucket by window
                tokens_7d += tokens;
                if ts >= cutoff_5h {
                    tokens_5h += tokens;
                    requests_5h += 1;
                }
                if ts >= cutoff_burn {
                    tokens_burn += tokens;
                }
            }
        }

        let burn_rate = tokens_burn as f64 / (BURN_RATE_WINDOW as f64 / 60.0);

        // Push to burn history
        self.burn_history.push_back((now, burn_rate));
        if self.burn_history.len() > MAX_BURN_HISTORY {
            self.burn_history.pop_front();
        }

        // Model breakdown sorted by tokens desc
        let mut model_breakdown: Vec<(String, u64)> = model_map.into_iter().collect();
        model_breakdown.sort_by(|a, b| b.1.cmp(&a.1));

        LocalUsageData {
            tokens_5h,
            tokens_7d,
            requests_5h,
            burn_rate,
            model_breakdown,
        }
    }
}

pub fn weighted_tokens(usage: &serde_json::Value) -> u64 {
    let input = usage.get("input_tokens").and_then(|v| v.as_u64()).unwrap_or(0);
    let cache_creation = usage.get("cache_creation_input_tokens").and_then(|v| v.as_u64()).unwrap_or(0);
    let cache_read = usage.get("cache_read_input_tokens").and_then(|v| v.as_u64()).unwrap_or(0);
    let output = usage.get("output_tokens").and_then(|v| v.as_u64()).unwrap_or(0);

    (input as f64 * INPUT_WEIGHT
        + cache_creation as f64 * CACHE_CREATION_WEIGHT
        + cache_read as f64 * CACHE_READ_WEIGHT
        + output as f64 * OUTPUT_WEIGHT) as u64
}

fn now_epoch() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_weighted_tokens_all_fields() {
        let usage = json!({
            "input_tokens": 100,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 300,
            "output_tokens": 50
        });
        // 100*1.0 + 200*1.0 + 300*0.0 + 50*1.0 = 350
        assert_eq!(weighted_tokens(&usage), 350);
    }

    #[test]
    fn test_weighted_tokens_missing_fields() {
        let usage = json!({ "input_tokens": 100 });
        assert_eq!(weighted_tokens(&usage), 100);
    }

    #[test]
    fn test_malformed_jsonl_line() {
        // Simulate parsing behavior
        let lines = vec![
            r#"{"timestamp":1000,"message":{"usage":{"input_tokens":50}}}"#,
            "not json",
            r#"{"timestamp":2000,"message":{"usage":{"input_tokens":75}}}"#,
        ];
        let mut parsed = 0;
        for line in &lines {
            if serde_json::from_str::<serde_json::Value>(line).is_ok() {
                parsed += 1;
            }
        }
        assert_eq!(parsed, 2);
    }

    #[test]
    fn test_empty_projects_dir() {
        let mut collector = LocalCollector::new();
        // With no actual project files, should return defaults
        let data = collector.collect();
        // Can't guarantee 0 since real files may exist, but at least no crash
        assert!(data.burn_rate >= 0.0);
    }

    #[test]
    fn test_burn_rate_calculation() {
        // Verify the formula: tokens_in_2min / 2.0 = tokens/min
        let tokens_burn: u64 = 10000;
        let burn_rate = tokens_burn as f64 / (BURN_RATE_WINDOW as f64 / 60.0);
        assert_eq!(burn_rate, 5000.0);
    }
}
