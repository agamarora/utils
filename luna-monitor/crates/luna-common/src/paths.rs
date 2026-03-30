use std::path::PathBuf;

fn home() -> Option<PathBuf> {
    dirs::home_dir()
}

pub fn luna_dir() -> Option<PathBuf> {
    home().map(|h| h.join(".luna-monitor"))
}

pub fn rate_limit_file() -> Option<PathBuf> {
    luna_dir().map(|d| d.join("rate-limits.jsonl"))
}

pub fn config_file() -> Option<PathBuf> {
    luna_dir().map(|d| d.join("config.json"))
}

pub fn proxy_pid_file() -> Option<PathBuf> {
    luna_dir().map(|d| d.join("proxy.pid"))
}

pub fn usage_cache_file() -> Option<PathBuf> {
    luna_dir().map(|d| d.join("usage-cache.json"))
}

pub fn calibrated_limits_file() -> Option<PathBuf> {
    luna_dir().map(|d| d.join("calibrated-limits.json"))
}

pub fn settings_json() -> Option<PathBuf> {
    home().map(|h| h.join(".claude").join("settings.json"))
}

pub fn settings_backup() -> Option<PathBuf> {
    luna_dir().map(|d| d.join("settings.json.backup"))
}

pub fn settings_lock() -> Option<PathBuf> {
    luna_dir().map(|d| d.join("settings.lock"))
}

pub fn credentials_path() -> Option<PathBuf> {
    home().map(|h| h.join(".claude").join(".credentials.json"))
}

pub fn claude_projects_dir() -> Option<PathBuf> {
    home().map(|h| h.join(".claude").join("projects"))
}

pub const DEFAULT_PORT: u16 = 9120;
pub const DEFAULT_TARGET: &str = "https://api.anthropic.com";
pub const MAX_JSONL_ENTRIES: usize = 1000;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_luna_dir_is_under_home() {
        if let Some(dir) = luna_dir() {
            assert!(dir.ends_with(".luna-monitor"));
        }
    }

    #[test]
    fn test_rate_limit_file_path() {
        if let Some(path) = rate_limit_file() {
            assert!(path.ends_with("rate-limits.jsonl"));
            assert!(path.parent().unwrap().ends_with(".luna-monitor"));
        }
    }

    #[test]
    fn test_settings_json_path() {
        if let Some(path) = settings_json() {
            assert!(path.ends_with("settings.json"));
            assert!(path.parent().unwrap().ends_with(".claude"));
        }
    }

    #[test]
    fn test_credentials_path() {
        if let Some(path) = credentials_path() {
            assert!(path.ends_with(".credentials.json"));
        }
    }
}
