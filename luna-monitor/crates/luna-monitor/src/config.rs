use luna_common::paths;
use serde::Deserialize;
use std::path::PathBuf;

fn default_refresh() -> f64 { 2.0 }
fn default_cache_ttl() -> u64 { 30 }
fn default_true() -> bool { true }
fn default_port() -> u16 { paths::DEFAULT_PORT }

fn default_drives() -> Vec<String> {
    if cfg!(target_os = "windows") {
        vec!["C:\\".to_string(), "D:\\".to_string()]
    } else {
        vec!["/".to_string()]
    }
}

#[derive(Debug, Deserialize)]
pub struct Config {
    #[serde(default = "default_refresh")]
    pub refresh_seconds: f64,
    #[serde(default = "default_cache_ttl")]
    pub cache_ttl_seconds: u64,
    #[serde(default = "default_drives")]
    pub drives: Vec<String>,
    #[serde(default = "default_true")]
    pub gpu_enabled: bool,
    #[serde(default = "default_true")]
    pub claude_enabled: bool,
    pub proxy_enabled: Option<bool>,
    #[serde(default = "default_port")]
    pub proxy_port: u16,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            refresh_seconds: default_refresh(),
            cache_ttl_seconds: default_cache_ttl(),
            drives: default_drives(),
            gpu_enabled: true,
            claude_enabled: true,
            proxy_enabled: None,
            proxy_port: default_port(),
        }
    }
}

impl Config {
    pub fn load() -> Self {
        let path = match paths::config_file() {
            Some(p) => p,
            None => return Config::default(),
        };
        Self::load_from(&path)
    }

    pub fn load_from(path: &PathBuf) -> Self {
        let content = match std::fs::read_to_string(path) {
            Ok(c) => c,
            Err(_) => return Config::default(),
        };
        let mut config: Config = match serde_json::from_str(&content) {
            Ok(c) => c,
            Err(_) => return Config::default(),
        };
        // Clamp refresh
        if config.refresh_seconds < 0.5 {
            config.refresh_seconds = 0.5;
        }
        config
    }

    pub fn save(&self) -> bool {
        let path = match paths::config_file() {
            Some(p) => p,
            None => return false,
        };
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        let json = match serde_json::to_string_pretty(self) {
            Ok(j) => j,
            Err(_) => return false,
        };
        std::fs::write(&path, json.as_bytes()).is_ok()
    }

    /// Tick interval in milliseconds
    pub fn tick_ms(&self) -> u64 {
        (self.refresh_seconds * 1000.0) as u64
    }
}

// Config needs Serialize for save()
impl serde::Serialize for Config {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeStruct;
        let mut s = serializer.serialize_struct("Config", 7)?;
        s.serialize_field("refresh_seconds", &self.refresh_seconds)?;
        s.serialize_field("cache_ttl_seconds", &self.cache_ttl_seconds)?;
        s.serialize_field("drives", &self.drives)?;
        s.serialize_field("gpu_enabled", &self.gpu_enabled)?;
        s.serialize_field("claude_enabled", &self.claude_enabled)?;
        s.serialize_field("proxy_enabled", &self.proxy_enabled)?;
        s.serialize_field("proxy_port", &self.proxy_port)?;
        s.end()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = Config::default();
        assert_eq!(config.refresh_seconds, 2.0);
        assert_eq!(config.cache_ttl_seconds, 30);
        assert!(config.gpu_enabled);
        assert!(config.claude_enabled);
        assert!(config.proxy_enabled.is_none());
        assert_eq!(config.proxy_port, 9120);
    }

    #[test]
    fn test_load_missing_file() {
        let config = Config::load_from(&PathBuf::from("/nonexistent/config.json"));
        assert_eq!(config.refresh_seconds, 2.0);
    }

    #[test]
    fn test_clamp_refresh() {
        let json = r#"{"refresh_seconds": 0.1}"#;
        let tmp = std::env::temp_dir().join("luna-test-config.json");
        std::fs::write(&tmp, json).unwrap();
        let config = Config::load_from(&tmp);
        assert_eq!(config.refresh_seconds, 0.5);
        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn test_partial_json() {
        let json = r#"{"gpu_enabled": false}"#;
        let tmp = std::env::temp_dir().join("luna-test-config2.json");
        std::fs::write(&tmp, json).unwrap();
        let config = Config::load_from(&tmp);
        assert!(!config.gpu_enabled);
        assert!(config.claude_enabled); // default
        assert_eq!(config.refresh_seconds, 2.0); // default
        let _ = std::fs::remove_file(&tmp);
    }
}
