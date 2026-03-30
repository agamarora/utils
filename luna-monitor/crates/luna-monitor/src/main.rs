#[allow(dead_code)]
mod app;
mod config;
#[allow(dead_code)]
mod collectors;
#[allow(dead_code)]
mod panels;
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
}

fn main() {
    let args = Args::parse();

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

    // --doctor
    if args.doctor {
        run_doctor();
        return;
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

fn run_doctor() {
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
    println!("1) Enable proxy (route Claude Code through luna-monitor for live usage %)");
    println!("2) Disable proxy (direct Claude Code, system metrics only)");
    println!("3) Reset everything (remove all luna-monitor config, restore vanilla Claude Code)");
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
                println!("Proxy enabled on port {}", port);
            } else {
                println!("Failed to start proxy");
            }
        }
        "2" => {
            let mut config = Config::load();
            config.proxy_enabled = Some(false);
            config.save();
            proxy_lifecycle::remove_proxy_setting();
            println!("Proxy disabled");
        }
        "3" => {
            proxy_lifecycle::remove_proxy_setting();
            if let Some(dir) = paths::luna_dir() {
                let _ = std::fs::remove_dir_all(&dir);
            }
            println!("Reset complete. All luna-monitor config removed.");
        }
        _ => {
            println!("Invalid choice");
        }
    }
}

fn check_update() {
    println!("Checking for updates...");
    println!("Current version: {}", env!("CARGO_PKG_VERSION"));
    println!("Auto-update requires a published GitHub release.");
    println!("Build from source or check releases for the latest version.");
}
