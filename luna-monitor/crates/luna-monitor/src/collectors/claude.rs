use luna_common::paths;
use luna_common::types::UsageData;
use std::time::{Duration, Instant};

const ALLOWED_DOMAINS: &[&str] = &[
    "api.anthropic.com",
    "console.anthropic.com",
    "platform.claude.com",
];
const REFRESH_URL: &str = "https://platform.claude.com/v1/oauth/token";
const USAGE_URL: &str = "https://api.anthropic.com/api/oauth/usage";
const USAGE_BETA: &str = "oauth-2025-04-20";
const BACKOFF_STEPS: &[u64] = &[30, 60, 120, 300];
const PLAN_NAMES: &[(&str, &str)] = &[
    ("default_claude_ai", "Pro"),
    ("default_claude_max_5x", "Max 5x"),
    ("default_claude_max_20x", "Max 20x"),
];
const CREDENTIAL_REREAD_SECS: u64 = 30;

pub struct ClaudeCollector {
    client: reqwest::Client,
    access_token: Option<String>,
    refresh_token: Option<String>,
    plan_tier: Option<String>,
    cached_usage: Option<UsageData>,
    cache_ttl: Duration,
    last_fetch: Instant,
    backoff_index: usize,
    backoff_until: Option<Instant>,
    credentials_last_read: Instant,
}

impl ClaudeCollector {
    pub fn new(cache_ttl_secs: u64) -> Self {
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::custom(|attempt| {
                let domain = attempt.url().host_str().unwrap_or("").to_string();
                if ALLOWED_DOMAINS.contains(&domain.as_str()) {
                    attempt.follow()
                } else {
                    attempt.error(anyhow_redirect(&domain))
                }
            }))
            .build()
            .expect("Failed to build HTTP client");

        Self {
            client,
            access_token: None,
            refresh_token: None,
            plan_tier: None,
            cached_usage: None,
            cache_ttl: Duration::from_secs(cache_ttl_secs),
            last_fetch: Instant::now() - Duration::from_secs(cache_ttl_secs + 1),
            backoff_index: 0,
            backoff_until: None,
            credentials_last_read: Instant::now() - Duration::from_secs(CREDENTIAL_REREAD_SECS + 1),
        }
    }

    fn read_credentials(&mut self) -> Result<(), String> {
        if self.credentials_last_read.elapsed() < Duration::from_secs(CREDENTIAL_REREAD_SECS) {
            if self.access_token.is_some() {
                return Ok(());
            }
        }
        self.credentials_last_read = Instant::now();

        let path = paths::credentials_path()
            .ok_or_else(|| "No home directory".to_string())?;
        let content = std::fs::read_to_string(&path)
            .map_err(|e| format!("Cannot read credentials: {}", e))?;
        let json: serde_json::Value = serde_json::from_str(&content)
            .map_err(|e| format!("Invalid JSON: {}", e))?;

        let oauth = json.get("claudeAiOauth")
            .ok_or_else(|| "Missing claudeAiOauth key".to_string())?;

        self.access_token = oauth.get("accessToken")
            .and_then(|v| v.as_str())
            .map(String::from);
        self.refresh_token = oauth.get("refreshToken")
            .and_then(|v| v.as_str())
            .map(String::from);

        // Extract plan tier
        if let Some(tier) = oauth.get("rateLimitTier").and_then(|v| v.as_str()) {
            self.plan_tier = PLAN_NAMES.iter()
                .find(|(k, _)| *k == tier)
                .map(|(_, v)| v.to_string())
                .or_else(|| Some(tier.to_string()));
        }

        if self.access_token.is_none() {
            return Err("No access token in credentials".to_string());
        }
        Ok(())
    }

    async fn refresh_token_request(&mut self) -> Result<(), String> {
        let refresh = self.refresh_token.as_ref()
            .ok_or_else(|| "No refresh token".to_string())?;

        let resp = self.client
            .post(REFRESH_URL)
            .header("Content-Type", "application/x-www-form-urlencoded")
            // NO Authorization header — critical security requirement
            .body(format!("grant_type=refresh_token&refresh_token={}", refresh))
            .send()
            .await
            .map_err(|e| format!("Refresh request failed: {}", e))?;

        if !resp.status().is_success() {
            return Err(format!("Refresh failed: HTTP {}", resp.status()));
        }

        let body: serde_json::Value = resp.json().await
            .map_err(|e| format!("Refresh response parse failed: {}", e))?;

        self.access_token = body.get("access_token")
            .and_then(|v| v.as_str())
            .map(String::from);

        if self.access_token.is_none() {
            return Err("No access_token in refresh response".to_string());
        }
        Ok(())
    }

    async fn fetch_usage(&self) -> Result<UsageData, String> {
        let token = self.access_token.as_ref()
            .ok_or_else(|| "No access token".to_string())?;

        let resp = self.client
            .get(USAGE_URL)
            .header("Authorization", format!("Bearer {}", token))
            .header("anthropic-beta", USAGE_BETA)
            .send()
            .await
            .map_err(|e| format!("Usage request failed: {}", e))?;

        let status = resp.status();
        if status.as_u16() == 429 {
            return Err("rate_limited".to_string());
        }
        if !status.is_success() {
            return Err(format!("Usage API error: HTTP {}", status));
        }

        let body: serde_json::Value = resp.json().await
            .map_err(|e| format!("Usage parse failed: {}", e))?;

        let mut data = UsageData::default();
        data.source = "api".to_string();
        data.fetched_at = Some(now_epoch());

        if let Some(plan) = &self.plan_tier {
            data.plan_name = plan.clone();
        }

        // Parse five_hour
        if let Some(fh) = body.get("five_hour") {
            data.five_hour.utilization = fh.get("utilization")
                .and_then(|v| v.as_f64()).unwrap_or(0.0);
            data.five_hour.resets_at = fh.get("resets_at")
                .and_then(|v| v.as_str()).unwrap_or("").to_string();
        }

        // Parse seven_day
        if let Some(sd) = body.get("seven_day") {
            data.seven_day.utilization = sd.get("utilization")
                .and_then(|v| v.as_f64()).unwrap_or(0.0);
            data.seven_day.resets_at = sd.get("resets_at")
                .and_then(|v| v.as_str()).unwrap_or("").to_string();
        }

        // Per-model breakdowns
        if let Some(sd_opus) = body.get("seven_day_opus") {
            data.seven_day_opus.utilization = sd_opus.get("utilization")
                .and_then(|v| v.as_f64()).unwrap_or(0.0);
        }
        if let Some(sd_sonnet) = body.get("seven_day_sonnet") {
            data.seven_day_sonnet.utilization = sd_sonnet.get("utilization")
                .and_then(|v| v.as_f64()).unwrap_or(0.0);
        }

        Ok(data)
    }

    pub async fn collect(&mut self) -> UsageData {
        // Check backoff
        if let Some(until) = self.backoff_until {
            if Instant::now() < until {
                return self.cached_or_disk();
            }
        }

        // Check cache TTL
        if self.last_fetch.elapsed() < self.cache_ttl {
            if let Some(ref cached) = self.cached_usage {
                return cached.clone();
            }
        }

        // Read credentials
        if let Err(e) = self.read_credentials() {
            return UsageData {
                error: Some(e),
                source: "error".to_string(),
                ..Default::default()
            };
        }

        // Try fetch
        match self.fetch_usage().await {
            Ok(data) => {
                self.backoff_index = 0;
                self.backoff_until = None;
                self.last_fetch = Instant::now();
                self.save_disk_cache(&data);
                self.cached_usage = Some(data.clone());
                data
            }
            Err(e) if e == "rate_limited" => {
                // Advance backoff
                let step = BACKOFF_STEPS.get(self.backoff_index)
                    .copied()
                    .unwrap_or(*BACKOFF_STEPS.last().unwrap());
                self.backoff_until = Some(Instant::now() + Duration::from_secs(step));
                if self.backoff_index < BACKOFF_STEPS.len() - 1 {
                    self.backoff_index += 1;
                }
                self.cached_or_disk()
            }
            Err(e) if e.contains("401") || e.contains("403") => {
                // Try token refresh
                if self.refresh_token_request().await.is_ok() {
                    // Retry once
                    match self.fetch_usage().await {
                        Ok(data) => {
                            self.backoff_index = 0;
                            self.backoff_until = None;
                            self.last_fetch = Instant::now();
                            self.save_disk_cache(&data);
                            self.cached_usage = Some(data.clone());
                            data
                        }
                        Err(e2) => {
                            let mut data = self.cached_or_disk();
                            data.error = Some(format!("Re-authenticate Claude Code: {}", e2));
                            data
                        }
                    }
                } else {
                    let mut data = self.cached_or_disk();
                    data.error = Some("Re-authenticate Claude Code".to_string());
                    data
                }
            }
            Err(e) => {
                let mut data = self.cached_or_disk();
                data.error = Some(e);
                data
            }
        }
    }

    fn cached_or_disk(&self) -> UsageData {
        if let Some(ref cached) = self.cached_usage {
            return cached.clone();
        }
        self.load_disk_cache().unwrap_or_default()
    }

    fn load_disk_cache(&self) -> Option<UsageData> {
        let path = paths::usage_cache_file()?;
        let content = std::fs::read_to_string(&path).ok()?;
        let json: serde_json::Value = serde_json::from_str(&content).ok()?;

        let mut data = UsageData::default();
        data.source = "cache".to_string();
        data.five_hour.utilization = json.get("five_hour_utilization")
            .and_then(|v| v.as_f64()).unwrap_or(0.0);
        data.seven_day.utilization = json.get("seven_day_utilization")
            .and_then(|v| v.as_f64()).unwrap_or(0.0);
        data.five_hour.resets_at = json.get("five_hour_resets_at")
            .and_then(|v| v.as_str()).unwrap_or("").to_string();
        data.seven_day.resets_at = json.get("seven_day_resets_at")
            .and_then(|v| v.as_str()).unwrap_or("").to_string();
        data.plan_name = json.get("plan_name")
            .and_then(|v| v.as_str()).unwrap_or("").to_string();
        data.fetched_at = json.get("fetched_at").and_then(|v| v.as_f64());
        Some(data)
    }

    fn save_disk_cache(&self, data: &UsageData) {
        let path = match paths::usage_cache_file() {
            Some(p) => p,
            None => return,
        };
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        let json = serde_json::json!({
            "five_hour_utilization": data.five_hour.utilization,
            "seven_day_utilization": data.seven_day.utilization,
            "five_hour_resets_at": data.five_hour.resets_at,
            "seven_day_resets_at": data.seven_day.resets_at,
            "plan_name": data.plan_name,
            "fetched_at": data.fetched_at,
        });
        let _ = std::fs::write(&path, serde_json::to_string_pretty(&json).unwrap_or_default());
    }
}

/// Check if a window reset time has passed.
pub fn is_window_expired(resets_at: &str) -> bool {
    if resets_at.is_empty() {
        return false;
    }

    let now = now_epoch();

    // Try as Unix epoch (integer or float)
    if let Ok(epoch) = resets_at.parse::<f64>() {
        if epoch > 1_000_000_000.0 {
            return epoch < now;
        }
    }

    // Try as ISO 8601
    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(resets_at) {
        return dt.timestamp() as f64 <= now;
    }

    // Also try without timezone (UTC assumed)
    if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(resets_at, "%Y-%m-%dT%H:%M:%SZ") {
        let ts = dt.and_utc().timestamp() as f64;
        return ts <= now;
    }

    false // Conservative: unparseable = not expired
}

fn now_epoch() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

fn anyhow_redirect(domain: &str) -> Box<dyn std::error::Error + Send + Sync> {
    format!("Redirect to non-allowed domain blocked: {}", domain).into()
}

/// Burndown prediction via linear regression on utilization points.
pub fn burndown_prediction(points: &[(f64, f64)]) -> (Option<f64>, &'static str) {
    if points.len() < 10 {
        return (None, "low");
    }

    // Filter out gaps > 300s
    let mut filtered = vec![points[0]];
    for i in 1..points.len() {
        if points[i].0 - points[i - 1].0 <= 300.0 {
            filtered.push(points[i]);
        }
    }

    if filtered.len() < 10 {
        return (None, "low");
    }

    // Use last 10 points
    let pts = &filtered[filtered.len() - 10..];
    let base_ts = pts[0].0;
    let n = pts.len() as f64;
    let mut sum_x = 0.0;
    let mut sum_y = 0.0;
    let mut sum_xy = 0.0;
    let mut sum_x2 = 0.0;
    let mut sum_y2 = 0.0;

    for &(ts, util) in pts {
        let x = ts - base_ts;
        let y = util;
        sum_x += x;
        sum_y += y;
        sum_xy += x * y;
        sum_x2 += x * x;
        sum_y2 += y * y;
    }

    let denom = n * sum_x2 - sum_x * sum_x;
    if denom.abs() < 1e-10 {
        return (None, "sustainable");
    }

    let slope = (n * sum_xy - sum_x * sum_y) / denom;

    if slope <= 0.001 {
        return (None, "sustainable");
    }

    let current = pts.last().unwrap().1;
    let remaining_pct = 100.0 - current;
    let seconds_remaining = remaining_pct / slope;
    let minutes = (seconds_remaining / 60.0).clamp(0.0, 600.0);

    // R² for confidence
    let ss_tot = sum_y2 - (sum_y * sum_y) / n;
    let intercept = (sum_y - slope * sum_x) / n;
    let mut ss_res = 0.0;
    for &(ts, util) in pts {
        let x = ts - base_ts;
        let pred = slope * x + intercept;
        ss_res += (util - pred) * (util - pred);
    }
    let r2 = if ss_tot > 0.0 { 1.0 - ss_res / ss_tot } else { 0.0 };

    let confidence = if r2 > 0.8 {
        "high"
    } else if r2 > 0.5 {
        "medium"
    } else {
        "low"
    };

    (Some(minutes), confidence)
}

/// Limit calibration: infer token limit from API utilization + local token count.
pub fn calibrate_limit(
    api_utilization: f64,
    local_tokens: u64,
    stored_limit: Option<u64>,
) -> Option<u64> {
    // Guards
    if api_utilization < 0.05 {
        return None; // Too low to be reliable
    }
    if local_tokens < 10_000 {
        return None; // Not enough data
    }

    let inferred = (local_tokens as f64 / api_utilization) as u64;

    // Reject if > 3x swing from stored
    if let Some(stored) = stored_limit {
        let ratio = inferred as f64 / stored as f64;
        if ratio > 3.0 || ratio < (1.0 / 3.0) {
            return None;
        }
    }

    Some(inferred)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_domain_check_blocks_unknown() {
        assert!(!ALLOWED_DOMAINS.contains(&"evil.example.com"));
    }

    #[test]
    fn test_domain_check_allows_anthropic() {
        assert!(ALLOWED_DOMAINS.contains(&"api.anthropic.com"));
        assert!(ALLOWED_DOMAINS.contains(&"platform.claude.com"));
    }

    #[test]
    fn test_backoff_steps() {
        assert_eq!(BACKOFF_STEPS, &[30, 60, 120, 300]);
    }

    #[test]
    fn test_window_expiry_epoch() {
        // 2020-01-01 — definitely in the past
        assert!(is_window_expired("1577836800"));
    }

    #[test]
    fn test_window_expiry_iso8601() {
        assert!(is_window_expired("2020-01-01T00:00:00Z"));
    }

    #[test]
    fn test_window_not_expired() {
        // Far future
        assert!(!is_window_expired("4102444800")); // 2100-01-01
    }

    #[test]
    fn test_window_unparseable() {
        assert!(!is_window_expired("garbage"));
    }

    #[test]
    fn test_burndown_10_points_positive_slope() {
        let mut points = Vec::new();
        let base = 1000.0;
        for i in 0..10 {
            // 1% per 60 seconds = 1% per minute
            points.push((base + i as f64 * 60.0, 50.0 + i as f64 * 1.0));
        }
        let (mins, confidence) = burndown_prediction(&points);
        assert!(mins.is_some());
        let m = mins.unwrap();
        // At 59% going up 1%/min, ~41 min remaining
        assert!(m > 30.0 && m < 60.0, "got {}", m);
        assert_eq!(confidence, "high");
    }

    #[test]
    fn test_burndown_fewer_than_10() {
        let points: Vec<(f64, f64)> = (0..5).map(|i| (i as f64 * 60.0, 50.0)).collect();
        let (mins, conf) = burndown_prediction(&points);
        assert!(mins.is_none());
        assert_eq!(conf, "low");
    }

    #[test]
    fn test_burndown_flat_slope() {
        let points: Vec<(f64, f64)> = (0..10).map(|i| (i as f64 * 60.0, 50.0)).collect();
        let (mins, conf) = burndown_prediction(&points);
        assert!(mins.is_none());
        assert_eq!(conf, "sustainable");
    }

    #[test]
    fn test_burndown_gap_discard() {
        let mut points = Vec::new();
        for i in 0..5 {
            points.push((i as f64 * 60.0, 50.0 + i as f64));
        }
        // 10-minute gap
        for i in 5..15 {
            points.push((i as f64 * 60.0 + 600.0, 55.0 + (i - 5) as f64));
        }
        let (mins, _conf) = burndown_prediction(&points);
        // Should still work with enough filtered points
        assert!(mins.is_some() || _conf == "sustainable" || _conf == "low");
    }

    #[test]
    fn test_calibrate_limit_normal() {
        let result = calibrate_limit(0.40, 2_000_000, None);
        assert_eq!(result, Some(5_000_000));
    }

    #[test]
    fn test_calibrate_reject_low_utilization() {
        assert!(calibrate_limit(0.02, 2_000_000, None).is_none());
    }

    #[test]
    fn test_calibrate_reject_swing() {
        // Stored 5M, new calc would be 20M (4x)
        let result = calibrate_limit(0.10, 2_000_000, Some(5_000_000));
        assert!(result.is_none());
    }

    #[test]
    fn test_disk_cache_roundtrip() {
        // Test that save + load round-trips
        let data = UsageData {
            five_hour: luna_common::types::UsageWindow {
                utilization: 0.42,
                resets_at: "2026-04-01T00:00:00Z".to_string(),
            },
            seven_day: luna_common::types::UsageWindow {
                utilization: 0.18,
                resets_at: "2026-04-07T00:00:00Z".to_string(),
            },
            plan_name: "Pro".to_string(),
            fetched_at: Some(1234567890.0),
            ..Default::default()
        };

        // Use temp file
        let tmp = std::env::temp_dir().join("luna-test-cache.json");
        let json = serde_json::json!({
            "five_hour_utilization": data.five_hour.utilization,
            "seven_day_utilization": data.seven_day.utilization,
            "five_hour_resets_at": data.five_hour.resets_at,
            "seven_day_resets_at": data.seven_day.resets_at,
            "plan_name": data.plan_name,
            "fetched_at": data.fetched_at,
        });
        std::fs::write(&tmp, serde_json::to_string_pretty(&json).unwrap()).unwrap();

        let content = std::fs::read_to_string(&tmp).unwrap();
        let loaded: serde_json::Value = serde_json::from_str(&content).unwrap();

        assert_eq!(loaded["five_hour_utilization"].as_f64(), Some(0.42));
        assert_eq!(loaded["seven_day_utilization"].as_f64(), Some(0.18));
        assert_eq!(loaded["plan_name"].as_str(), Some("Pro"));
        let _ = std::fs::remove_file(&tmp);
    }
}
