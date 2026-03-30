use std::path::PathBuf;

/// Base directory: ~/.luna-tt/
pub fn base_dir() -> Option<PathBuf> {
    dirs::home_dir().map(|h| h.join(".luna-tt"))
}

/// Ensure base directory exists
pub fn ensure_base_dir() -> Option<PathBuf> {
    let dir = base_dir()?;
    std::fs::create_dir_all(&dir).ok()?;
    Some(dir)
}

/// Rate limits JSONL: ~/.luna-tt/rate-limits.jsonl
pub fn rate_limit_file() -> Option<PathBuf> {
    base_dir().map(|d| d.join("rate-limits.jsonl"))
}

/// Growth state: ~/.luna-tt/growth.json
pub fn growth_state_file() -> Option<PathBuf> {
    base_dir().map(|d| d.join("growth.json"))
}

/// Config file: ~/.luna-tt/config.json
pub fn config_file() -> Option<PathBuf> {
    base_dir().map(|d| d.join("config.json"))
}

/// PID file for the proxy process: ~/.luna-tt/proxy.pid
pub fn proxy_pid_file() -> Option<PathBuf> {
    base_dir().map(|d| d.join("proxy.pid"))
}

/// Claude Code settings.json: ~/.claude/settings.json
pub fn claude_settings_file() -> Option<PathBuf> {
    dirs::home_dir().map(|h| h.join(".claude").join("settings.json"))
}
