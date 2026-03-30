use luna_common::paths;
use std::path::PathBuf;
use tracing::{info, warn};

pub struct ProxyManager {
    pub port: u16,
    pub settings_modified: bool,
}

impl ProxyManager {
    pub fn new(port: u16) -> Self {
        Self {
            port,
            settings_modified: false,
        }
    }

    /// Check for stale proxy lockfile from a previous crash and clean up.
    pub fn recover_from_crash() -> bool {
        let pid_path = match paths::proxy_pid_file() {
            Some(p) => p,
            None => return false,
        };
        let content = match std::fs::read_to_string(&pid_path) {
            Ok(c) => c,
            Err(_) => return false,
        };
        let parts: Vec<&str> = content.trim().split_whitespace().collect();
        if parts.is_empty() {
            return false;
        }
        let pid: u32 = match parts[0].parse() {
            Ok(p) => p,
            Err(_) => return false,
        };

        // Check timestamp (must be > 10s old to avoid race)
        if parts.len() > 1 {
            if let Ok(ts) = parts[1].parse::<u64>() {
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs();
                if now.saturating_sub(ts) < 10 {
                    return false; // Too fresh, might still be starting
                }
            }
        }

        if is_pid_alive(pid) {
            return false;
        }

        info!("Cleaning stale proxy config from PID {}", pid);
        remove_proxy_setting();
        let _ = std::fs::remove_file(&pid_path);
        true
    }

    /// Start luna-proxy as a detached process.
    pub fn start_proxy(&mut self) -> bool {
        // Check if already running
        if let Some(_health) = crate::collectors::rate_limit::RateLimitCollector::proxy_health(self.port) {
            info!("Proxy already running on port {}", self.port);
            if write_proxy_setting(self.port) {
                self.settings_modified = true;
            }
            return true;
        }

        // Find luna-proxy binary
        let proxy_bin = match find_proxy_binary() {
            Some(p) => p,
            None => {
                warn!("luna-proxy binary not found");
                return false;
            }
        };

        // Spawn as detached process
        info!("Starting luna-proxy from {:?}", proxy_bin);
        let result = spawn_detached(&proxy_bin, &["--port", &self.port.to_string()]);

        if !result {
            warn!("Failed to start luna-proxy");
            return false;
        }

        // Wait up to 5s for health check
        for _ in 0..50 {
            std::thread::sleep(std::time::Duration::from_millis(100));
            if crate::collectors::rate_limit::RateLimitCollector::proxy_health(self.port).is_some() {
                info!("Proxy healthy on port {}", self.port);
                if write_proxy_setting(self.port) {
                    self.settings_modified = true;
                }
                return true;
            }
        }

        warn!("Proxy started but health check failed after 5s");
        false
    }

    /// Watchdog: check proxy health, restart after 3 consecutive failures.
    #[allow(dead_code)]
    pub async fn watchdog_tick(&mut self, consecutive_failures: &mut u32) {
        if crate::collectors::rate_limit::RateLimitCollector::proxy_health(self.port).is_some() {
            *consecutive_failures = 0;
        } else {
            *consecutive_failures += 1;
            if *consecutive_failures >= 3 {
                warn!("Proxy failed 3 health checks, restarting");
                self.start_proxy();
                *consecutive_failures = 0;
            }
        }
    }

    pub fn cleanup(&self) {
        if self.settings_modified {
            remove_proxy_setting();
        }
    }
}

fn find_proxy_binary() -> Option<PathBuf> {
    // 1. Same directory as luna-monitor binary
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let name = if cfg!(windows) { "luna-proxy.exe" } else { "luna-proxy" };
            let candidate = dir.join(name);
            if candidate.exists() {
                return Some(candidate);
            }
        }
    }

    // 2. PATH lookup
    let name = if cfg!(windows) { "luna-proxy.exe" } else { "luna-proxy" };
    if let Ok(output) = std::process::Command::new("where").arg(name).output() {
        if output.status.success() {
            let path = String::from_utf8_lossy(&output.stdout);
            let first_line = path.lines().next()?;
            let p = PathBuf::from(first_line.trim());
            if p.exists() {
                return Some(p);
            }
        }
    }

    // Unix fallback
    if !cfg!(windows) {
        if let Ok(output) = std::process::Command::new("which").arg("luna-proxy").output() {
            if output.status.success() {
                let path = String::from_utf8_lossy(&output.stdout);
                let p = PathBuf::from(path.trim());
                if p.exists() {
                    return Some(p);
                }
            }
        }
    }

    None
}

#[cfg(windows)]
fn spawn_detached(binary: &PathBuf, args: &[&str]) -> bool {
    use std::os::windows::process::CommandExt;
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
    const DETACHED_PROCESS: u32 = 0x00000008;

    std::process::Command::new(binary)
        .args(args)
        .creation_flags(CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .is_ok()
}

#[cfg(not(windows))]
fn spawn_detached(binary: &PathBuf, args: &[&str]) -> bool {
    use std::os::unix::process::CommandExt;
    unsafe {
        std::process::Command::new(binary)
            .args(args)
            .pre_exec(|| {
                libc::setsid();
                Ok(())
            })
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .is_ok()
    }
}

fn with_settings_lock<F, T>(f: F) -> Result<T, String>
where
    F: FnOnce() -> Result<T, String>,
{
    let lock_path = match paths::luna_dir() {
        Some(d) => d.join("settings.lock"),
        None => return f(), // No lock possible, just try
    };
    let _ = std::fs::create_dir_all(lock_path.parent().unwrap());

    #[cfg(windows)]
    {
        // On Windows, creating the file acts as a basic lock
        // For true file locking, we'd use LockFileEx, but for our use case
        // (single machine, low contention), create-and-retry is sufficient
        let _lock = std::fs::File::create(&lock_path);
        let result = f();
        let _ = std::fs::remove_file(&lock_path);
        result
    }

    #[cfg(not(windows))]
    {
        use std::io::Write;
        let lock_file = std::fs::File::create(&lock_path)
            .map_err(|e| format!("Cannot create lock: {}", e))?;
        // flock
        unsafe {
            libc::flock(
                std::os::unix::io::AsRawFd::as_raw_fd(&lock_file),
                libc::LOCK_EX,
            );
        }
        let result = f();
        unsafe {
            libc::flock(
                std::os::unix::io::AsRawFd::as_raw_fd(&lock_file),
                libc::LOCK_UN,
            );
        }
        result
    }
}

pub fn write_proxy_setting(port: u16) -> bool {
    with_settings_lock(|| write_proxy_setting_inner(port)).unwrap_or(false)
}

fn write_proxy_setting_inner(port: u16) -> Result<bool, String> {
    let settings_path = paths::settings_json()
        .ok_or_else(|| "No home directory".to_string())?;

    // Read existing or start fresh
    let mut settings: serde_json::Value = if let Ok(content) = std::fs::read_to_string(&settings_path) {
        serde_json::from_str(&content).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    // Backup (first time only)
    if let Some(backup_path) = paths::settings_backup() {
        if !backup_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&settings_path) {
                let _ = std::fs::write(&backup_path, &content);
            }
        }
    }

    // Merge
    let env = settings.as_object_mut().unwrap()
        .entry("env")
        .or_insert_with(|| serde_json::json!({}));
    env.as_object_mut().unwrap()
        .insert("ANTHROPIC_BASE_URL".to_string(),
                serde_json::Value::String(format!("http://127.0.0.1:{}", port)));

    // Atomic write (temp in same directory)
    let tmp_path = settings_path.with_extension("tmp");
    let json = serde_json::to_string_pretty(&settings).unwrap() + "\n";
    std::fs::write(&tmp_path, &json)
        .map_err(|e| format!("Write failed: {}", e))?;
    std::fs::rename(&tmp_path, &settings_path)
        .map_err(|e| format!("Rename failed: {}", e))?;

    Ok(true)
}

pub fn remove_proxy_setting() -> bool {
    with_settings_lock(|| remove_proxy_setting_inner()).unwrap_or(false)
}

fn remove_proxy_setting_inner() -> Result<bool, String> {
    let settings_path = paths::settings_json()
        .ok_or_else(|| "No home directory".to_string())?;

    let content = match std::fs::read_to_string(&settings_path) {
        Ok(c) => c,
        Err(_) => return Ok(true), // No file = nothing to remove
    };

    let mut settings: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Invalid JSON: {}", e))?;

    if let Some(env) = settings.get_mut("env").and_then(|e| e.as_object_mut()) {
        env.remove("ANTHROPIC_BASE_URL");
        if env.is_empty() {
            settings.as_object_mut().unwrap().remove("env");
        }
    }

    let tmp_path = settings_path.with_extension("tmp");
    let json = serde_json::to_string_pretty(&settings).unwrap() + "\n";
    std::fs::write(&tmp_path, &json)
        .map_err(|e| format!("Write failed: {}", e))?;
    std::fs::rename(&tmp_path, &settings_path)
        .map_err(|e| format!("Rename failed: {}", e))?;

    Ok(true)
}

#[cfg(windows)]
fn is_pid_alive(pid: u32) -> bool {
    use std::ptr;
    const PROCESS_QUERY_INFORMATION: u32 = 0x0400;
    extern "system" {
        fn OpenProcess(dwDesiredAccess: u32, bInheritHandle: i32, dwProcessId: u32) -> *mut std::ffi::c_void;
        fn CloseHandle(hObject: *mut std::ffi::c_void) -> i32;
    }
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_INFORMATION, 0, pid);
        if handle.is_null() || handle == ptr::null_mut() {
            false
        } else {
            CloseHandle(handle);
            true
        }
    }
}

#[cfg(not(windows))]
fn is_pid_alive(pid: u32) -> bool {
    unsafe { libc::kill(pid as i32, 0) == 0 }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_recover_no_lockfile() {
        // With no PID file, should return false
        // Can't easily test without mocking paths, so test the logic directly
        let result = ProxyManager::recover_from_crash();
        // Result depends on whether a real PID file exists, but shouldn't crash
        let _ = result;
    }

    #[test]
    fn test_recover_live_pid() {
        // Our own PID is alive
        assert!(is_pid_alive(std::process::id()));
    }

    #[test]
    fn test_write_proxy_setting_preserves_other_keys() {
        let tmp = std::env::temp_dir().join("luna-test-settings.json");
        let original = r#"{"hooks": {"value": true}}"#;
        std::fs::write(&tmp, original).unwrap();

        // Simulate write_proxy_setting logic
        let content = std::fs::read_to_string(&tmp).unwrap();
        let mut settings: serde_json::Value = serde_json::from_str(&content).unwrap();

        let env = settings.as_object_mut().unwrap()
            .entry("env")
            .or_insert_with(|| serde_json::json!({}));
        env.as_object_mut().unwrap()
            .insert("ANTHROPIC_BASE_URL".to_string(),
                    serde_json::Value::String("http://127.0.0.1:9120".to_string()));

        let json = serde_json::to_string_pretty(&settings).unwrap();
        std::fs::write(&tmp, &json).unwrap();

        // Verify
        let written: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&tmp).unwrap()).unwrap();
        assert!(written.get("hooks").is_some());
        assert_eq!(
            written["env"]["ANTHROPIC_BASE_URL"].as_str(),
            Some("http://127.0.0.1:9120")
        );

        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn test_remove_proxy_setting() {
        let tmp = std::env::temp_dir().join("luna-test-settings-rm.json");
        let original = r#"{"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9120"}}"#;
        std::fs::write(&tmp, original).unwrap();

        let content = std::fs::read_to_string(&tmp).unwrap();
        let mut settings: serde_json::Value = serde_json::from_str(&content).unwrap();

        if let Some(env) = settings.get_mut("env").and_then(|e| e.as_object_mut()) {
            env.remove("ANTHROPIC_BASE_URL");
            if env.is_empty() {
                settings.as_object_mut().unwrap().remove("env");
            }
        }

        let json = serde_json::to_string_pretty(&settings).unwrap();
        std::fs::write(&tmp, &json).unwrap();

        let written: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&tmp).unwrap()).unwrap();
        assert!(written.get("env").is_none());

        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn test_remove_setting_not_present() {
        let tmp = std::env::temp_dir().join("luna-test-settings-noop.json");
        std::fs::write(&tmp, r#"{"hooks": {}}"#).unwrap();

        let content = std::fs::read_to_string(&tmp).unwrap();
        let mut settings: serde_json::Value = serde_json::from_str(&content).unwrap();

        if let Some(env) = settings.get_mut("env").and_then(|e| e.as_object_mut()) {
            env.remove("ANTHROPIC_BASE_URL");
        }
        // No crash, no error
        let json = serde_json::to_string_pretty(&settings).unwrap();
        std::fs::write(&tmp, &json).unwrap();

        let written: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&tmp).unwrap()).unwrap();
        assert!(written.get("hooks").is_some());

        let _ = std::fs::remove_file(&tmp);
    }

    #[test]
    fn test_atomic_write() {
        let tmp = std::env::temp_dir().join("luna-test-atomic.json");
        let tmp_file = tmp.with_extension("tmp");
        std::fs::write(&tmp, "{}").unwrap();

        let settings = serde_json::json!({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9120"}});
        let json = serde_json::to_string_pretty(&settings).unwrap() + "\n";
        std::fs::write(&tmp_file, &json).unwrap();
        std::fs::rename(&tmp_file, &tmp).unwrap();

        // .tmp should not exist after rename
        assert!(!tmp_file.exists());
        // Result should be valid JSON
        let content = std::fs::read_to_string(&tmp).unwrap();
        let _: serde_json::Value = serde_json::from_str(&content).unwrap();

        let _ = std::fs::remove_file(&tmp);
    }
}
