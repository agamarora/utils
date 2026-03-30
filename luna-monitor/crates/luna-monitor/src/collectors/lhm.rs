//! LibreHardwareMonitor HTTP client.
//! Auto-detects LHM at localhost:8085/data.json.
//! Provides: real CPU frequency, CPU temps, GPU temp.
//! If LHM is not running, all functions return None.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use crate::collectors::gpu::GpuData;

const LHM_URL: &str = "http://localhost:8085/data.json";
const LHM_TIMEOUT: Duration = Duration::from_secs(2);
const LHM_CACHE_SECS: u64 = 10;

#[derive(Debug, Clone, Default)]
pub struct LhmData {
    pub cpu_clocks: HashMap<String, f64>,  // "CPU Core #1" -> MHz
    // Specific temp fields instead of generic HashMap
    pub cpu_package_temp: Option<f32>,
    pub cpu_max_temp: Option<f32>,
    pub cpu_avg_temp: Option<f32>,
    pub gpu_temp: Option<f32>,  // Stored independently, not on GpuData
    pub gpu: Option<GpuData>,
}

impl LhmData {
    pub fn avg_cpu_mhz(&self) -> Option<f64> {
        if self.cpu_clocks.is_empty() {
            return None;
        }
        let sum: f64 = self.cpu_clocks.values().sum();
        Some(sum / self.cpu_clocks.len() as f64)
    }

    pub fn avg_cpu_freq_ghz_str(&self) -> Option<String> {
        self.avg_cpu_mhz().map(|mhz| format!("{:.2} GHz", mhz / 1000.0))
    }
}

static CACHE: Mutex<Option<(Instant, LhmData)>> = Mutex::new(None);

/// Fetch LHM data. Cached for 10 seconds. Returns None if LHM is not running.
pub fn fetch() -> Option<LhmData> {
    let mut cache = CACHE.lock().ok()?;

    if let Some((ts, ref data)) = *cache {
        if ts.elapsed() < Duration::from_secs(LHM_CACHE_SECS) {
            return Some(data.clone());
        }
    }

    let data = fetch_inner()?;
    *cache = Some((Instant::now(), data.clone()));
    Some(data)
}

/// Check if LHM is available (cached result).
pub fn is_available() -> bool {
    fetch().is_some()
}

fn fetch_inner() -> Option<LhmData> {
    let client = reqwest::blocking::Client::builder()
        .timeout(LHM_TIMEOUT)
        .build()
        .ok()?;

    let resp = client.get(LHM_URL).send().ok()?;
    if !resp.status().is_success() {
        return None;
    }

    let root: serde_json::Value = resp.json().ok()?;
    let mut data = LhmData::default();
    parse_node(&root, &mut data, &[]);
    Some(data)
}

fn parse_node(node: &serde_json::Value, data: &mut LhmData, path: &[String]) {
    let text = node.get("Text").and_then(|v| v.as_str()).unwrap_or("");
    let value_str = node.get("Value").and_then(|v| v.as_str()).unwrap_or("");

    // Track path for GPU detection
    let mut current_path = path.to_vec();
    current_path.push(text.to_string());
    let in_gpu = current_path.iter().any(|p| {
        let lower = p.to_lowercase();
        lower.contains("gpu") || lower.contains("nvidia") || lower.contains("radeon")
    });

    // CPU clocks: "MHz" in value + "CPU Core" in text
    if value_str.contains("MHz") && text.contains("CPU Core") {
        if let Some(mhz) = parse_numeric(value_str, "MHz") {
            data.cpu_clocks.insert(text.to_string(), mhz);
        }
    }

    // Temperatures: "°C" in value — use substring matching for vendor compatibility
    if value_str.contains("°C") || value_str.contains("\u{00b0}C") {
        if let Some(celsius) = parse_numeric(value_str, "°C")
            .or_else(|| parse_numeric(value_str, "\u{00b0}C"))
        {
            if celsius > 0.0 && celsius < 120.0 {
                let text_lower = text.to_lowercase();

                if in_gpu && text_lower.contains("gpu core") {
                    // GPU Core temp — stored independently
                    data.gpu_temp = Some(celsius as f32);
                } else if !in_gpu {
                    // CPU temps — substring match for Intel + AMD compatibility
                    if text_lower.contains("package") || text_lower.contains("tdie") {
                        data.cpu_package_temp = Some(celsius as f32);
                    } else if text_lower.contains("core max") {
                        data.cpu_max_temp = Some(celsius as f32);
                    } else if text_lower.contains("core average") {
                        data.cpu_avg_temp = Some(celsius as f32);
                    }
                }
            }
        }
    }

    // GPU utilization: "%" in value under GPU path
    if in_gpu && value_str.contains('%') && text.contains("GPU Core") {
        if let Some(pct) = parse_numeric(value_str, "%") {
            let gpu = data.gpu.get_or_insert_with(|| GpuData {
                name: current_path.iter()
                    .find(|p| p.to_lowercase().contains("nvidia") || p.to_lowercase().contains("radeon") || p.to_lowercase().contains("gpu"))
                    .cloned()
                    .unwrap_or_else(|| "GPU".to_string()),
                utilization_pct: 0,
                vram_used_mb: 0,
                vram_total_mb: 0,
                temp_celsius: 0,
            });
            gpu.utilization_pct = pct as u32;
        }
    }

    // GPU memory
    if in_gpu && text.contains("GPU Memory") && value_str.contains("MB") {
        if let Some(mb) = parse_numeric(value_str, "MB") {
            let gpu = data.gpu.get_or_insert_with(|| GpuData {
                name: "GPU".to_string(),
                utilization_pct: 0,
                vram_used_mb: 0,
                vram_total_mb: 0,
                temp_celsius: 0,
            });
            if text.contains("Used") || text.contains("used") {
                gpu.vram_used_mb = mb as u64;
            } else if text.contains("Total") || text.contains("total") {
                gpu.vram_total_mb = mb as u64;
            }
        }
    }

    // Recurse into children
    if let Some(children) = node.get("Children").and_then(|c| c.as_array()) {
        for child in children {
            parse_node(child, data, &current_path);
        }
    }
}

fn parse_numeric(value_str: &str, suffix: &str) -> Option<f64> {
    let cleaned = value_str
        .replace(suffix, "")
        .replace(',', ".")
        .trim()
        .to_string();
    cleaned.parse::<f64>().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_numeric() {
        assert_eq!(parse_numeric("42.5 MHz", "MHz"), Some(42.5));
        assert_eq!(parse_numeric("65 °C", "°C"), Some(65.0));
        assert_eq!(parse_numeric("95.3 %", "%"), Some(95.3));
        assert_eq!(parse_numeric("not a number", "MHz"), None);
    }

    #[test]
    fn test_lhm_data_avg_cpu() {
        let mut data = LhmData::default();
        data.cpu_clocks.insert("CPU Core #1".to_string(), 4200.0);
        data.cpu_clocks.insert("CPU Core #2".to_string(), 4100.0);
        data.cpu_clocks.insert("CPU Core #3".to_string(), 4300.0);
        assert_eq!(data.avg_cpu_mhz(), Some(4200.0));
        assert_eq!(data.avg_cpu_freq_ghz_str(), Some("4.20 GHz".to_string()));
    }

    #[test]
    fn test_lhm_data_empty() {
        let data = LhmData::default();
        assert!(data.avg_cpu_mhz().is_none());
        assert!(data.gpu.is_none());
        assert!(data.cpu_package_temp.is_none());
        assert!(data.gpu_temp.is_none());
    }

    #[test]
    fn test_lhm_unavailable() {
        let result = fetch_inner();
        let _ = result;
    }

    #[test]
    fn test_parse_node_with_specific_temps() {
        let json = serde_json::json!({
            "Text": "Root",
            "Value": "",
            "Children": [
                {
                    "Text": "12th Gen Intel Core i5-12400F",
                    "Value": "",
                    "Children": [
                        {
                            "Text": "Temperatures",
                            "Value": "",
                            "Children": [
                                {"Text": "CPU Core #1", "Value": "4200 MHz", "Children": []},
                                {"Text": "CPU Package", "Value": "45 °C", "Children": []},
                                {"Text": "Core Max", "Value": "52 °C", "Children": []},
                                {"Text": "Core Average", "Value": "38 °C", "Children": []}
                            ]
                        }
                    ]
                },
                {
                    "Text": "NVIDIA GeForce RTX 3060 Ti",
                    "Value": "",
                    "Children": [
                        {
                            "Text": "Temperatures",
                            "Value": "",
                            "Children": [
                                {"Text": "GPU Core", "Value": "44 °C", "Children": []}
                            ]
                        }
                    ]
                }
            ]
        });

        let mut data = LhmData::default();
        parse_node(&json, &mut data, &[]);

        assert_eq!(data.cpu_package_temp, Some(45.0));
        assert_eq!(data.cpu_max_temp, Some(52.0));
        assert_eq!(data.cpu_avg_temp, Some(38.0));
        assert_eq!(data.gpu_temp, Some(44.0));
    }

    #[test]
    fn test_gpu_temp_before_gpu_util() {
        // GPU temp node appears BEFORE GPU utilization node
        // gpu_temp should still be captured (stored independently)
        let json = serde_json::json!({
            "Text": "Root",
            "Value": "",
            "Children": [
                {
                    "Text": "NVIDIA GeForce RTX 3060 Ti",
                    "Value": "",
                    "Children": [
                        {
                            "Text": "Temperatures",
                            "Value": "",
                            "Children": [
                                {"Text": "GPU Core", "Value": "44 °C", "Children": []}
                            ]
                        },
                        {
                            "Text": "Load",
                            "Value": "",
                            "Children": [
                                {"Text": "GPU Core", "Value": "25 %", "Children": []}
                            ]
                        }
                    ]
                }
            ]
        });

        let mut data = LhmData::default();
        parse_node(&json, &mut data, &[]);

        // gpu_temp is stored independently, not on GpuData
        assert_eq!(data.gpu_temp, Some(44.0));
        // GpuData should also exist from the utilization node
        assert!(data.gpu.is_some());
        assert_eq!(data.gpu.as_ref().unwrap().utilization_pct, 25);
    }
}
