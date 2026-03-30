mod health;
mod jsonl;
mod proxy;

use bytes::Bytes;
use clap::Parser;
use http_body_util::Full;
use hyper::body::Incoming;
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request, Response};
use hyper_util::rt::TokioIo;
use luna_common::paths;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::net::TcpListener;
use tracing::{error, info};

#[derive(Parser)]
#[command(name = "luna-proxy", version, about = "Transparent proxy for capturing Anthropic rate limit headers")]
struct Args {
    #[arg(long, default_value_t = paths::DEFAULT_PORT)]
    port: u16,

    #[arg(long, default_value = paths::DEFAULT_TARGET)]
    target: String,

    #[arg(long, help = "Enable debug logging")]
    verbose: bool,
}

#[tokio::main]
async fn main() {
    let args = Args::parse();

    // Init tracing
    let level = if args.verbose { "debug" } else { "info" };
    tracing_subscriber::fmt()
        .with_env_filter(level)
        .init();

    // Ensure ~/.luna-monitor/ exists
    if let Some(dir) = paths::luna_dir() {
        let _ = std::fs::create_dir_all(&dir);
    }

    // Rotate JSONL
    if let Some(path) = paths::rate_limit_file() {
        jsonl::rotate(&path, paths::MAX_JSONL_ENTRIES);
    }

    // Write PID file
    write_pid_file();

    // Clean stale lockfile from previous crash
    clean_stale_settings();

    // Register shutdown handler
    let (shutdown_tx, mut shutdown_rx) = tokio::sync::oneshot::channel::<()>();
    let shutdown_tx = Arc::new(std::sync::Mutex::new(Some(shutdown_tx)));
    let shutdown_tx_clone = shutdown_tx.clone();
    ctrlc::set_handler(move || {
        info!("Shutting down...");
        remove_pid_file();
        if let Some(tx) = shutdown_tx_clone.lock().unwrap().take() {
            let _ = tx.send(());
        }
    })
    .expect("Failed to set Ctrl-C handler");

    // Build proxy state
    let jsonl_path = paths::rate_limit_file().expect("Cannot determine home directory");
    let state = Arc::new(proxy::ProxyState::new(
        args.target.trim_end_matches('/').to_string(),
        jsonl_path,
    ));

    // Try binding to port, fall back to port+1 through port+9
    let mut bound_port = None;
    for p in args.port..args.port + 10 {
        let addr = SocketAddr::from(([127, 0, 0, 1], p));
        match TcpListener::bind(addr).await {
            Ok(listener) => {
                info!("luna-proxy listening on 127.0.0.1:{}", p);
                bound_port = Some((listener, p));
                break;
            }
            Err(e) => {
                if p == args.port {
                    info!("Port {} in use ({}), trying next...", p, e);
                }
            }
        }
    }

    let (listener, _port) = match bound_port {
        Some(v) => v,
        None => {
            error!("Could not bind to any port {}-{}", args.port, args.port + 9);
            remove_pid_file();
            std::process::exit(1);
        }
    };

    // Serve connections
    loop {
        tokio::select! {
            result = listener.accept() => {
                match result {
                    Ok((stream, _addr)) => {
                        let state = state.clone();
                        tokio::spawn(async move {
                            let io = TokioIo::new(stream);
                            let service = service_fn(move |req: Request<Incoming>| {
                                let state = state.clone();
                                async move {
                                    route(req, state).await
                                }
                            });
                            if let Err(e) = http1::Builder::new()
                                .serve_connection(io, service)
                                .await
                            {
                                tracing::debug!("Connection error: {}", e);
                            }
                        });
                    }
                    Err(e) => {
                        error!("Accept error: {}", e);
                    }
                }
            }
            _ = &mut shutdown_rx => {
                info!("Shutdown signal received");
                break;
            }
        }
    }

    remove_pid_file();
}

async fn route(
    req: Request<Incoming>,
    state: Arc<proxy::ProxyState>,
) -> Result<Response<Full<Bytes>>, hyper::Error> {
    if req.uri().path() == "/health" && req.method() == hyper::Method::GET {
        health::handle(req, state).await
    } else {
        proxy::handle(req, state).await
    }
}

fn write_pid_file() {
    if let Some(path) = paths::proxy_pid_file() {
        let pid = std::process::id();
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let _ = std::fs::write(&path, format!("{} {}", pid, ts));
    }
}

fn remove_pid_file() {
    if let Some(path) = paths::proxy_pid_file() {
        let _ = std::fs::remove_file(&path);
    }
}

fn clean_stale_settings() {
    let pid_path = match paths::proxy_pid_file() {
        Some(p) => p,
        None => return,
    };
    let content = match std::fs::read_to_string(&pid_path) {
        Ok(c) => c,
        Err(_) => return,
    };
    let parts: Vec<&str> = content.trim().split_whitespace().collect();
    if parts.is_empty() {
        return;
    }
    let pid: u32 = match parts[0].parse() {
        Ok(p) => p,
        Err(_) => return,
    };

    // Check if PID is alive
    if is_pid_alive(pid) {
        return; // Not stale
    }

    // Stale lockfile — clean up settings.json
    info!("Cleaning stale proxy config from PID {}", pid);
    remove_anthropic_base_url();
    let _ = std::fs::remove_file(&pid_path);
}

fn remove_anthropic_base_url() {
    let settings_path = match paths::settings_json() {
        Some(p) => p,
        None => return,
    };
    let content = match std::fs::read_to_string(&settings_path) {
        Ok(c) => c,
        Err(_) => return,
    };
    let mut settings: serde_json::Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(_) => return,
    };

    if let Some(env) = settings.get_mut("env").and_then(|e| e.as_object_mut()) {
        if env.remove("ANTHROPIC_BASE_URL").is_some() {
            if env.is_empty() {
                settings.as_object_mut().unwrap().remove("env");
            }
            // Atomic write: same directory as target
            let tmp_path = settings_path.with_extension("tmp");
            let json = serde_json::to_string_pretty(&settings).unwrap() + "\n";
            if std::fs::write(&tmp_path, &json).is_ok() {
                let _ = std::fs::rename(&tmp_path, &settings_path);
            }
        }
    }
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
