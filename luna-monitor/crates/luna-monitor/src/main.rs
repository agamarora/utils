#[allow(dead_code)]
mod app;
mod config;
#[allow(dead_code)]
mod collectors;
#[allow(dead_code)]
mod panels;
mod proxy;
mod proxy_lifecycle;
#[allow(dead_code)]
mod platform_win;
#[allow(dead_code)]
mod ui;

use clap::Parser;
use luna_common::paths;
use config::Config;
use proxy_lifecycle::ProxyManager;

#[derive(Parser)]
#[command(name = "luna-monitor", version, about = "Terminal dashboard for Claude Code developers")]
struct Args {
    #[arg(long, help = "Disable GPU panel")]
    no_gpu: bool,

    #[arg(long, help = "Disable Claude usage panels")]
    no_claude: bool,

    #[arg(long, default_value_t = 2.0, help = "Refresh interval in seconds")]
    refresh: f64,

    #[arg(long, help = "No network requests")]
    offline: bool,

    #[arg(long, help = "Write ANTHROPIC_BASE_URL to settings.json")]
    enable_proxy: bool,

    #[arg(long, help = "Remove ANTHROPIC_BASE_URL from settings.json")]
    disable_proxy: bool,

    #[arg(long, help = "Interactive proxy setup menu")]
    doctor: bool,

    #[arg(long, help = "Enable debug logging")]
    verbose: bool,

    #[arg(long, help = "Check for updates")]
    update: bool,

    // Hidden flag: run as embedded proxy server (spawned by proxy_lifecycle)
    #[arg(long, hide = true)]
    proxy_mode: bool,

    #[arg(long, default_value_t = paths::DEFAULT_PORT, hide = true)]
    port: u16,

    #[arg(long, default_value = paths::DEFAULT_TARGET, hide = true)]
    target: String,
}

fn main() {
    let args = Args::parse();

    // --proxy-mode: run as embedded proxy server (no dashboard)
    if args.proxy_mode {
        let level = if args.verbose { "debug" } else { "info" };
        tracing_subscriber::fmt()
            .with_env_filter(level)
            .init();
        run_proxy_mode(args.port, &args.target);
        return;
    }

    // Init tracing
    let level = if args.verbose { "debug" } else { "warn" };
    tracing_subscriber::fmt()
        .with_env_filter(level)
        .init();

    // --update
    if args.update {
        check_update();
        return;
    }

    // --doctor (launches dashboard after enable/disable)
    if args.doctor {
        if !run_doctor() {
            return; // option 3 (reset) — exit
        }
        // fall through to dashboard
    }

    // --enable-proxy / --disable-proxy
    if args.enable_proxy {
        let mut manager = ProxyManager::new(paths::DEFAULT_PORT);
        if manager.start_proxy() {
            println!("Proxy enabled on port {}", paths::DEFAULT_PORT);
        } else {
            eprintln!("Failed to start proxy");
            std::process::exit(1);
        }
        return;
    }
    if args.disable_proxy {
        proxy_lifecycle::remove_proxy_setting();
        println!("Proxy disabled");
        return;
    }

    // Load config
    let mut config = Config::load();

    // Apply CLI overrides
    if args.no_gpu {
        config.gpu_enabled = false;
    }
    if args.no_claude || args.offline {
        config.claude_enabled = false;
    }
    if args.refresh != 2.0 {
        config.refresh_seconds = args.refresh.max(0.5);
    }

    // First-run prompt
    if config.proxy_enabled.is_none() && config.claude_enabled && !args.offline {
        first_run_prompt(&mut config);
    }

    // Ensure ~/.luna-monitor/ exists
    if let Some(dir) = paths::luna_dir() {
        let _ = std::fs::create_dir_all(&dir);
    }

    // Crash recovery
    ProxyManager::recover_from_crash();

    // Setup proxy if enabled
    let mut proxy_manager = None;
    let mut usage_rx = None;

    if config.claude_enabled && config.proxy_enabled == Some(true) {
        let mut pm = ProxyManager::new(config.proxy_port);
        pm.start_proxy();
        proxy_manager = Some(pm);
    }

    // Background Claude collector
    if config.claude_enabled && !args.offline {
        let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
        let cache_ttl = config.cache_ttl_seconds;
        let refresh_secs = config.refresh_seconds;

        std::thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .enable_all()
                .build()
                .expect("Failed to create tokio runtime");

            rt.block_on(async {
                let mut collector = collectors::claude::ClaudeCollector::new(cache_ttl);
                loop {
                    let data = collector.collect().await;
                    if tx.send(data).is_err() {
                        break; // Main thread dropped receiver
                    }
                    tokio::time::sleep(tokio::time::Duration::from_secs_f64(refresh_secs)).await;
                }
            });
        });

        usage_rx = Some(rx);
    }

    // Run dashboard
    if let Err(e) = app::run(&config, usage_rx) {
        eprintln!("Error: {}", e);
    }

    // Cleanup
    if let Some(pm) = proxy_manager {
        pm.cleanup();
    }
}

/// Run as embedded proxy server. This is spawned by proxy_lifecycle as a detached process.
fn run_proxy_mode(port: u16, target: &str) {
    use hyper::body::Incoming;
    use hyper::server::conn::http1;
    use hyper::service::service_fn;
    use hyper::Request;
    use hyper_util::rt::TokioIo;
    use std::net::SocketAddr;
    use std::sync::Arc;
    use tracing::{error, info};

    let target = target.trim_end_matches('/').to_string();

    let rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .expect("Failed to create tokio runtime");

    rt.block_on(async {
        // Ensure ~/.luna-monitor/ exists
        if let Some(dir) = paths::luna_dir() {
            let _ = std::fs::create_dir_all(&dir);
        }

        // Rotate JSONL
        if let Some(path) = paths::rate_limit_file() {
            proxy::jsonl::rotate(&path, paths::MAX_JSONL_ENTRIES);
        }

        // Write PID file
        write_pid_file();

        // Clean stale lockfile
        clean_stale_settings();

        // Shutdown handler
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
        let state = Arc::new(proxy::server::ProxyState::new(target, jsonl_path));

        // Bind to port (try port through port+9)
        let mut bound_port = None;
        for p in port..port + 10 {
            let addr = SocketAddr::from(([127, 0, 0, 1], p));
            match tokio::net::TcpListener::bind(addr).await {
                Ok(listener) => {
                    info!("luna-monitor proxy listening on 127.0.0.1:{}", p);
                    bound_port = Some((listener, p));
                    break;
                }
                Err(e) => {
                    if p == port {
                        info!("Port {} in use ({}), trying next...", p, e);
                    }
                }
            }
        }

        let (listener, _port) = match bound_port {
            Some(v) => v,
            None => {
                error!("Could not bind to any port {}-{}", port, port + 9);
                remove_pid_file();
                std::process::exit(1);
            }
        };

        // Serve
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
    });
}

async fn route(
    req: hyper::Request<hyper::body::Incoming>,
    state: std::sync::Arc<proxy::server::ProxyState>,
) -> Result<hyper::Response<http_body_util::Full<bytes::Bytes>>, hyper::Error> {
    if req.uri().path() == "/health" && req.method() == hyper::Method::GET {
        proxy::health::handle(req, state).await
    } else {
        proxy::server::handle(req, state).await
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

    if is_pid_alive(pid) {
        return;
    }

    tracing::info!("Cleaning stale proxy config from PID {}", pid);
    proxy_lifecycle::remove_proxy_setting();
    let _ = std::fs::remove_file(&pid_path);
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

fn first_run_prompt(config: &mut Config) {
    println!("luna-monitor — first run setup");
    println!("───────────────────────────────");
    println!("luna-monitor can capture live usage data (session %, weekly %)");
    println!("by routing Claude Code's API calls through a local proxy.");
    println!();
    println!("This modifies ~/.claude/settings.json to add ANTHROPIC_BASE_URL.");
    println!("The proxy runs on 127.0.0.1 only and never inspects request bodies.");
    println!();
    print!("Enable live usage tracking? [Y/n]: ");
    use std::io::Write;
    std::io::stdout().flush().unwrap();

    let mut input = String::new();
    std::io::stdin().read_line(&mut input).unwrap_or(0);
    let trimmed = input.trim().to_lowercase();

    let enabled = trimmed.is_empty() || trimmed == "y" || trimmed == "yes";
    config.proxy_enabled = Some(enabled);
    config.save();

    if enabled {
        println!("Proxy enabled. Starting...");
    } else {
        println!("Proxy disabled. You can enable it later with: luna-monitor --doctor");
    }
    println!();
}

/// Returns true if dashboard should launch after, false to exit.
fn run_doctor() -> bool {
    let port = paths::DEFAULT_PORT;
    let proxy_running = collectors::rate_limit::RateLimitCollector::proxy_health(port).is_some();

    println!("luna-monitor doctor");
    println!("─────────────────");
    if proxy_running {
        println!("Current status: proxy enabled on port {} (healthy)", port);
    } else {
        println!("Current status: proxy not running");
    }
    println!();
    println!("1) Enable proxy and start dashboard");
    println!("2) Disable proxy and start dashboard (system metrics only)");
    println!("3) Reset everything (remove all config, exit)");
    println!();
    print!("Choose [1-3]: ");
    use std::io::Write;
    std::io::stdout().flush().unwrap();

    let mut input = String::new();
    std::io::stdin().read_line(&mut input).unwrap_or(0);

    match input.trim() {
        "1" => {
            let mut config = Config::load();
            config.proxy_enabled = Some(true);
            config.save();
            let mut pm = ProxyManager::new(port);
            if pm.start_proxy() {
                println!("Proxy enabled. Launching dashboard...");
                println!();
            } else {
                println!("Failed to start proxy. Launching dashboard without proxy...");
                println!();
            }
            true // launch dashboard
        }
        "2" => {
            let mut config = Config::load();
            config.proxy_enabled = Some(false);
            config.save();
            proxy_lifecycle::remove_proxy_setting();
            println!("Proxy disabled. Launching dashboard...");
            println!();
            true // launch dashboard
        }
        "3" => {
            proxy_lifecycle::remove_proxy_setting();
            if let Some(dir) = paths::luna_dir() {
                let _ = std::fs::remove_dir_all(&dir);
            }
            println!("Reset complete. All luna-monitor config removed.");
            false // exit
        }
        _ => {
            println!("Invalid choice");
            false
        }
    }
}

fn check_update() {
    println!("Checking for updates...");
    println!("Current version: {}", env!("CARGO_PKG_VERSION"));
    println!("Auto-update requires a published GitHub release.");
    println!("Build from source or check releases for the latest version.");
}
