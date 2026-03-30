use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    /// Proxy port range start (default 9130, avoids luna-monitor's 9120-9129)
    #[serde(default = "default_proxy_port")]
    pub proxy_port: u16,

    /// Data collection interval in seconds
    #[serde(default = "default_refresh")]
    pub refresh_seconds: f64,

    /// Animation frame interval in milliseconds
    #[serde(default = "default_frame_ms")]
    pub frame_ms: u64,

    /// Vertical split ratio for growth panel (0.0-1.0, default 0.5 = 50/50)
    #[serde(default = "default_growth_ratio")]
    pub growth_ratio: f64,

    /// Auto-save interval in seconds
    #[serde(default = "default_autosave")]
    pub autosave_seconds: u64,
}

fn default_proxy_port() -> u16 { 9130 }
fn default_refresh() -> f64 { 2.0 }
fn default_frame_ms() -> u64 { 150 }
fn default_growth_ratio() -> f64 { 0.5 }
fn default_autosave() -> u64 { 30 }

impl Default for Config {
    fn default() -> Self {
        Config {
            proxy_port: default_proxy_port(),
            refresh_seconds: default_refresh(),
            frame_ms: default_frame_ms(),
            growth_ratio: default_growth_ratio(),
            autosave_seconds: default_autosave(),
        }
    }
}

impl Config {
    pub fn load() -> Self {
        if let Some(path) = crate::paths::config_file() {
            if let Ok(content) = std::fs::read_to_string(&path) {
                if let Ok(config) = serde_json::from_str(&content) {
                    return config;
                }
            }
        }
        Config::default()
    }
}
