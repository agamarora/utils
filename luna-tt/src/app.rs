use crate::collectors::rate_limit::RateLimitCollector;
use crate::collectors::system::SystemCollector;
use crate::config::Config;
use crate::growth;
use crate::panels;
use crate::proxy_lifecycle::ProxyManager;
use crate::types::{ProxyEvent, UsageData};
use crossterm::event::{self, Event, KeyCode, KeyEventKind};
use crossterm::terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen};
use crossterm::ExecutableCommand;
use ratatui::layout::{Constraint, Direction, Layout};
use ratatui::Terminal;
use std::io::stdout;
use std::time::{Duration, Instant};

pub fn run() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::load();

    // Ensure base directory exists
    crate::paths::ensure_base_dir();

    // Load or create growth state
    let mut growth_state = growth::load_or_create();

    // Init system collector
    let mut sys_collector = SystemCollector::new();
    // First tick needs a brief delay for CPU measurement
    std::thread::sleep(Duration::from_millis(500));
    sys_collector.tick();

    // Init rate limit collector
    let rate_limit_path = crate::paths::rate_limit_file()
        .unwrap_or_else(|| std::path::PathBuf::from("rate-limits.jsonl"));
    let mut rl_collector = RateLimitCollector::new(rate_limit_path);

    // Spawn proxy
    let mut proxy = ProxyManager::new(config.proxy_port);
    proxy.spawn_proxy();

    // Set up terminal
    enable_raw_mode()?;
    stdout().execute(EnterAlternateScreen)?;
    let backend = ratatui::backend::CrosstermBackend::new(stdout());
    let mut terminal = Terminal::new(backend)?;
    terminal.hide_cursor()?;
    terminal.clear()?;

    // Set up Ctrl+C handler
    let running = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(true));
    let r = running.clone();
    let _ = ctrlc::set_handler(move || {
        r.store(false, std::sync::atomic::Ordering::SeqCst);
    });

    let frame_duration = Duration::from_millis(config.frame_ms);
    let refresh_interval = Duration::from_secs_f64(config.refresh_seconds);
    let autosave_interval = Duration::from_secs(config.autosave_seconds);

    let mut last_refresh = Instant::now() - refresh_interval; // force first collection
    let mut last_autosave = Instant::now();
    let mut last_proxy_ts: Option<String> = None;
    let mut usage_data = UsageData::default();
    let start_time = Instant::now();

    // Cached system metrics
    let mut cpu_pct = 0.0f64;
    let mut ram_pct = 0.0f64;
    let mut disk_pct = 0.0f64;
    let mut top_procs: Vec<(u32, String, f32)> = Vec::new();

    while running.load(std::sync::atomic::Ordering::SeqCst) {
        let frame_start = Instant::now();

        // Every refresh_seconds: collect system data, read JSONL, ingest events
        if last_refresh.elapsed() >= refresh_interval {
            sys_collector.tick();
            let morphs = sys_collector.morphs();
            cpu_pct = sys_collector.cpu_pct();
            ram_pct = sys_collector.ram_pct();
            disk_pct = sys_collector.disk_active_pct();
            top_procs = sys_collector.top_processes(5);

            // Read JSONL for latest entry
            if let Some(entry) = rl_collector.latest() {
                let ts = entry.ts.clone();
                let is_new = last_proxy_ts.as_ref() != Some(&ts);

                // Update usage data
                usage_data = UsageData {
                    five_hour_utilization: entry.five_h_utilization
                        .map(|v| if v > 1.0 { v / 100.0 } else { v })
                        .unwrap_or(0.0),
                    seven_day_utilization: entry.seven_d_utilization
                        .map(|v| if v > 1.0 { v / 100.0 } else { v })
                        .unwrap_or(0.0),
                    five_hour_reset: entry.five_h_reset.clone().unwrap_or_default(),
                    seven_day_reset: entry.seven_d_reset.clone().unwrap_or_default(),
                    source: "proxy".to_string(),
                    status: entry.status.clone().unwrap_or_else(|| "unknown".to_string()),
                };

                if is_new {
                    // Ingest proxy event
                    let event = ProxyEvent::from_entry(entry);
                    growth_state.trigger_pulse(event.seven_d_utilization);
                    growth_state.ingest(event);
                    last_proxy_ts = Some(ts);
                }
            } else {
                usage_data.source = "none".to_string();
            }

            // Update morphs for growth
            growth_state.tick(&morphs);
            last_refresh = Instant::now();
        } else {
            // Tick growth with cached morphs (for animation)
            let morphs = sys_collector.morphs();
            growth_state.tick(&morphs);
        }

        // Autosave
        if last_autosave.elapsed() >= autosave_interval {
            if let Some(path) = crate::paths::growth_state_file() {
                let _ = growth_state.save(&path);
            }
            last_autosave = Instant::now();
        }

        // Render
        let wall_time = start_time.elapsed().as_secs_f64();
        let morphs = sys_collector.morphs();
        let usage_clone = usage_data.clone();
        let procs_clone = top_procs.clone();

        terminal.draw(|frame| {
            let size = frame.area();

            // Split: growth_ratio for top, rest for bottom
            let growth_pct = (config.growth_ratio * 100.0).round() as u16;
            let chunks = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Percentage(growth_pct),
                    Constraint::Percentage(100 - growth_pct),
                ])
                .split(size);

            // Top: growth panel
            growth_state.render(frame, chunks[0], wall_time, &morphs);

            // Bottom: monitor panels sub-split
            let monitor_chunks = Layout::default()
                .direction(Direction::Vertical)
                .constraints([
                    Constraint::Length(5),  // Claude status
                    Constraint::Length(5),  // System bar
                    Constraint::Min(3),    // Processes
                ])
                .split(chunks[1]);

            panels::claude_status::render(frame, monitor_chunks[0], &usage_clone, None);
            panels::system_bar::render(frame, monitor_chunks[1], cpu_pct, ram_pct, disk_pct);
            panels::processes::render(frame, monitor_chunks[2], &procs_clone);
        })?;

        // Input: poll for 'q' to quit
        let elapsed = frame_start.elapsed();
        let remaining = frame_duration.saturating_sub(elapsed);
        if remaining > Duration::ZERO {
            if event::poll(remaining)? {
                if let Event::Key(key) = event::read()? {
                    if key.kind == KeyEventKind::Press && key.code == KeyCode::Char('q') {
                        break;
                    }
                }
            }
        }
    }

    // Clean exit: save growth state
    if let Some(path) = crate::paths::growth_state_file() {
        let _ = growth_state.save(&path);
    }

    // Cleanup proxy
    proxy.cleanup();

    // Restore terminal
    terminal.show_cursor()?;
    disable_raw_mode()?;
    stdout().execute(LeaveAlternateScreen)?;

    Ok(())
}
