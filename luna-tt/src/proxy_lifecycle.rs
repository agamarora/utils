use crate::paths;
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
                    return false;
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

    /// Spawn the proxy as a detached process. Try ports 9130-9139.
    pub fn spawn_proxy(&mut self) -> bool {
        // Clean up any stale state
        Self::recover_from_crash();

        // Try port range 9130-9139
        for port_offset in 0..10u16 {
            let port = self.port + port_offset;

            // Check if already running on this port
            if check_proxy_health(port) {
                info!("Proxy already running on port {}", port);
                self.port = port;
                if write_proxy_setting(port) {
                    self.settings_modified = true;
                }
                return true;
            }

            // Try to spawn on this port
            let self_exe = match std::env::current_exe() {
                Ok(p) => p,
                Err(e) => {
                    warn!("Cannot find own executable: {}", e);
                    return false;
                }
            };

            info!("Starting embedded proxy on port {} from {:?}", port, self_exe);
            let result = spawn_detached(&self_exe, &["--proxy-mode"]);
            if !result {
                warn!("Failed to spawn proxy process");
                continue;
            }

            // Wait up to 5s for health check
            for _ in 0..50 {
                std::thread::sleep(std::time::Duration::from_millis(100));
                if check_proxy_health(port) {
                    info!("Proxy healthy on port {}", port);
                    self.port = port;
                    if write_proxy_setting(port) {
                        self.settings_modified = true;
                    }
                    return true;
                }
            }

            warn!("Proxy on port {} didn't become healthy, trying next port", port);
        }

        warn!("Failed to start proxy on any port in range");
        false
    }

    /// Cleanup: remove settings.json entry and PID file.
    pub fn cleanup(&self) {
        if self.settings_modified {
            remove_proxy_setting();
        }
        // Kill the proxy process if we have a PID
        if let Some(pid_path) = paths::proxy_pid_file() {
            if let Ok(content) = std::fs::read_to_string(&pid_path) {
                if let Ok(pid) = content.trim().split_whitespace().next().unwrap_or("").parse::<u32>() {
                    kill_pid(pid);
                }
            }
            let _ = std::fs::remove_file(&pid_path);
        }
    }
}

/// Check proxy health by making an HTTP request to /health.
fn check_proxy_health(port: u16) -> bool {
    std::net::TcpStream::connect_timeout(
        &std::net::SocketAddr::from(([127, 0, 0, 1], port)),
        std::time::Duration::from_millis(500),
    ).is_ok()
}

/// Write ANTHROPIC_BASE_URL to ~/.claude/settings.json (atomic: write temp, rename).
fn write_proxy_setting(port: u16) -> bool {
    let settings_path = match paths::claude_settings_file() {
        Some(p) => p,
        None => return false,
    };

    (|| -> Result<bool, String> {
        // Ensure parent directory exists
        if let Some(parent) = settings_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| format!("mkdir: {}", e))?;
        }

        // Read existing or start fresh
        let mut settings: serde_json::Value = if let Ok(content) = std::fs::read_to_string(&settings_path) {
            serde_json::from_str(&content).unwrap_or_else(|_| serde_json::json!({}))
        } else {
            serde_json::json!({})
        };

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
    })().unwrap_or(false)
}

/// Remove ANTHROPIC_BASE_URL from ~/.claude/settings.json.
fn remove_proxy_setting() -> bool {
    let settings_path = match paths::claude_settings_file() {
        Some(p) => p,
        None => return false,
    };

    (|| -> Result<bool, String> {
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
    })().unwrap_or(false)
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
    std::process::Command::new(binary)
        .args(args)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .is_ok()
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
fn is_pid_alive(_pid: u32) -> bool {
    false // Stub for non-Windows
}

#[cfg(windows)]
fn kill_pid(pid: u32) {
    extern "system" {
        fn OpenProcess(dwDesiredAccess: u32, bInheritHandle: i32, dwProcessId: u32) -> *mut std::ffi::c_void;
        fn TerminateProcess(hProcess: *mut std::ffi::c_void, uExitCode: u32) -> i32;
        fn CloseHandle(hObject: *mut std::ffi::c_void) -> i32;
    }
    const PROCESS_TERMINATE: u32 = 0x0001;
    unsafe {
        let handle = OpenProcess(PROCESS_TERMINATE, 0, pid);
        if !handle.is_null() {
            TerminateProcess(handle, 0);
            CloseHandle(handle);
        }
    }
}

#[cfg(not(windows))]
fn kill_pid(_pid: u32) {
    // Stub for non-Windows
}
