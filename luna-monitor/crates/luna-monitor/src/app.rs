use std::io;
use std::time::Duration;

use crossterm::event::{self, Event, KeyCode, KeyEventKind};
use crossterm::execute;
use crossterm::terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen};
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use ratatui::Terminal;

use luna_common::types::{ProxyHealth, UsageData, LocalUsageData};
use crate::collectors::system::SystemCollector;
use crate::collectors::gpu::{GpuCollector, GpuData};
use crate::collectors::claude_local::LocalCollector;
use crate::collectors::rate_limit::RateLimitCollector;
use crate::collectors::lhm::{self, LhmData};
use crate::config::Config;
use crate::panels;
use crate::platform_win;

pub struct AppState {
    pub system: SystemCollector,
    pub gpu_collector: GpuCollector,
    pub gpu_data: Option<GpuData>,
    pub local_collector: LocalCollector,
    pub rate_limit_collector: RateLimitCollector,
    pub usage: UsageData,
    pub local_usage: LocalUsageData,
    pub proxy_health: Option<ProxyHealth>,
    pub lhm_data: Option<LhmData>,
    pub disk_active: std::collections::HashMap<String, f64>,
    // Pace tracking: last 3 (epoch_secs, pct) readings
    pub pace_history: Vec<(f64, f64)>,
    // GPU temp tracking (session max/avg since LHM only gives current)
    pub gpu_temp_max: f32,
    pub gpu_temp_samples: Vec<f32>,
    // Last fresh proxy timestamp (epoch secs) for staleness display
    pub last_proxy_ts: Option<f64>,
}

pub fn run(config: &Config, usage_rx: Option<tokio::sync::mpsc::UnboundedReceiver<UsageData>>) -> io::Result<()> {
    // Init terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // Init PDH for disk active %
    platform_win::init_pdh(&config.drives);

    // Init collectors
    let gpu_collector = GpuCollector::try_init().unwrap_or_else(|| {
        #[cfg(not(feature = "gpu"))]
        { GpuCollector }
        #[cfg(feature = "gpu")]
        { unreachable!() }
    });

    let mut state = AppState {
        system: SystemCollector::new(),
        gpu_collector,
        gpu_data: None,
        local_collector: LocalCollector::new(),
        rate_limit_collector: RateLimitCollector::new(),
        usage: UsageData::default(),
        local_usage: LocalUsageData::default(),
        proxy_health: None,
        lhm_data: None,
        disk_active: std::collections::HashMap::new(),
        pace_history: Vec::new(),
        gpu_temp_max: 0.0,
        gpu_temp_samples: Vec::new(),
        last_proxy_ts: None,
    };

    // Prime CPU counters
    state.system.tick();
    std::thread::sleep(Duration::from_secs(1));

    let mut usage_rx = usage_rx;
    let tick_ms = config.tick_ms();

    loop {
        // Check for new usage data from API background task
        if let Some(ref mut rx) = usage_rx {
            while let Ok(data) = rx.try_recv() {
                // API always provides per-model breakdown (proxy doesn't have this)
                state.usage.seven_day_opus = data.seven_day_opus.clone();
                state.usage.seven_day_sonnet = data.seven_day_sonnet.clone();
                state.usage.fetched_at = data.fetched_at;
                state.usage.error = data.error.clone();

                // API only overwrites utilization if proxy has been dead (>10 min)
                let proxy_dead = state.last_proxy_ts
                    .map(|ts| {
                        let now = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64();
                        now - ts > 600.0
                    })
                    .unwrap_or(true); // no proxy data ever seen

                if proxy_dead {
                    let u = data.five_hour.utilization;
                    let pct = if u > 1.0 { u } else { u * 100.0 };
                    let now = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64();
                    state.pace_history.push((now, pct));
                    if state.pace_history.len() > 3 {
                        state.pace_history.remove(0);
                    }
                    state.usage.five_hour = data.five_hour;
                    state.usage.seven_day = data.seven_day;
                    state.usage.source = data.source;
                }
            }
        }

        // Sync collectors
        state.system.tick();
        state.lhm_data = lhm::fetch();
        state.gpu_data = state.gpu_collector.collect();
        state.local_usage = state.local_collector.collect();
        state.disk_active = platform_win::collect_disk_active();

        // GPU temp merge: prefer LHM when available and non-zero
        if let Some(ref lhm) = state.lhm_data {
            if let Some(lhm_gpu_temp) = lhm.gpu_temp {
                if lhm_gpu_temp > 0.0 {
                    if let Some(ref mut gpu) = state.gpu_data {
                        gpu.temp_celsius = lhm_gpu_temp as u32;
                    }
                    // Track GPU temp max/avg over session
                    if lhm_gpu_temp > state.gpu_temp_max {
                        state.gpu_temp_max = lhm_gpu_temp;
                    }
                    state.gpu_temp_samples.push(lhm_gpu_temp);
                    // Keep last 300 samples (~10 min at 2s tick)
                    if state.gpu_temp_samples.len() > 300 {
                        state.gpu_temp_samples.remove(0);
                    }
                }
            }
        }

        if let Some(entry) = state.rate_limit_collector.collect() {
            if state.rate_limit_collector.is_fresh() {
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64();
                state.last_proxy_ts = Some(now);

                if let Some(util) = entry.five_h_utilization {
                    // Track pace from proxy data (normalize to 0-100)
                    let pct = if util > 1.0 { util } else { util * 100.0 };
                    state.pace_history.push((now, pct));
                    if state.pace_history.len() > 3 {
                        state.pace_history.remove(0);
                    }
                    state.usage.five_hour.utilization = util;
                }
                if let Some(util) = entry.seven_d_utilization {
                    state.usage.seven_day.utilization = util;
                }
                if let Some(ref reset) = entry.five_h_reset {
                    state.usage.five_hour.resets_at = reset.clone();
                }
                if let Some(ref reset) = entry.seven_d_reset {
                    state.usage.seven_day.resets_at = reset.clone();
                }
                state.usage.source = "proxy".to_string();
            }
        }

        // Check proxy health
        state.proxy_health = RateLimitCollector::proxy_health(config.proxy_port);

        // Render
        terminal.draw(|frame| {
            let size = frame.area();
            let min_height = if config.claude_enabled { 30 } else { 25 };
            if size.width < 60 || size.height < min_height {
                let msg = Paragraph::new(Line::from(Span::styled(
                    format!("Resize terminal (min 60x{}, current {}x{})", min_height, size.width, size.height),
                    Style::default().fg(Color::Yellow),
                )));
                frame.render_widget(msg, size);
                return;
            }
            render(frame, size, &state, config);
        })?;

        // Poll for input
        if event::poll(Duration::from_millis(tick_ms))? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press && key.code == KeyCode::Char('q') {
                    break;
                }
            }
        }
    }

    // Restore terminal
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;

    Ok(())
}

/// Compute pace string from last 3 (epoch, pct) readings.
fn compute_pace(history: &[(f64, f64)]) -> &'static str {
    if history.len() < 2 {
        return "";
    }
    let (_, pct_last) = history[history.len() - 1];
    let (_, pct_prev) = history[history.len() - 2];
    let delta = pct_last - pct_prev;
    if delta > 2.0 {
        "↑ rising"
    } else if delta < -2.0 {
        "↓ falling"
    } else {
        "→ steady"
    }
}

/// Compute ETA to cap from current utilization and window reset time.
/// Uses: rate = current_pct / elapsed_in_window, then extrapolates to 100%.
fn compute_eta(current_pct: f64, resets_at: &str) -> String {
    if current_pct < 0.1 {
        return String::new(); // nothing to extrapolate
    }

    // Parse resets_at to get seconds until reset
    let secs_until_reset = parse_reset_secs(resets_at);
    if secs_until_reset <= 0.0 {
        return String::new();
    }

    let window_total: f64 = 5.0 * 3600.0; // 5h window in seconds
    let elapsed = window_total - secs_until_reset;
    if elapsed < 60.0 {
        return String::new(); // window just started, too noisy
    }

    // rate in %/sec based on average consumption so far
    let rate = current_pct / elapsed;
    let remaining_pct = 100.0 - current_pct;
    let eta_secs = remaining_pct / rate;

    if eta_secs <= 0.0 {
        return "at cap".to_string();
    }

    let total_min = (eta_secs / 60.0) as u64;
    if total_min >= 60 {
        format!("ETA ~{}h {}m to cap", total_min / 60, total_min % 60)
    } else if total_min > 0 {
        format!("ETA ~{}m to cap", total_min)
    } else {
        "ETA <1m to cap".to_string()
    }
}

/// Parse resets_at string into seconds remaining. Returns 0 on failure.
fn parse_reset_secs(resets_at: &str) -> f64 {
    if resets_at.is_empty() {
        return 0.0;
    }
    // Try epoch
    if let Ok(epoch) = resets_at.parse::<f64>() {
        if epoch > 1_000_000_000.0 {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64();
            return (epoch - now).max(0.0);
        }
    }
    // Try ISO 8601
    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(resets_at) {
        let remaining = dt.signed_duration_since(chrono::Utc::now());
        return remaining.num_seconds().max(0) as f64;
    }
    // Try UTC without timezone
    if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(resets_at, "%Y-%m-%dT%H:%M:%SZ") {
        let remaining = dt.signed_duration_since(chrono::Utc::now().naive_utc());
        return remaining.num_seconds().max(0) as f64;
    }
    0.0
}

fn render(frame: &mut ratatui::Frame, area: Rect, state: &AppState, config: &Config) {
    let mut constraints = Vec::new();
    let claude_enabled = config.claude_enabled;

    if claude_enabled {
        constraints.push(Constraint::Length(8));  // Claude Status (includes net line)
        constraints.push(Constraint::Length(4));  // CPU + Temps (side by side, 2 border + 2 content)
        constraints.push(Constraint::Length(5));  // Memory + GPU (GPU needs 3 content lines)
        constraints.push(Constraint::Length(6));  // Disks
        constraints.push(Constraint::Min(5));     // Processes
    } else {
        constraints.push(Constraint::Length(4));  // CPU + Temps
        constraints.push(Constraint::Length(5));  // Memory + GPU
        constraints.push(Constraint::Length(3));  // Network (compact)
        constraints.push(Constraint::Length(6));  // Disks
        constraints.push(Constraint::Min(8));     // Processes
    }

    let chunks = Layout::vertical(constraints).split(area);
    let mut idx = 0;

    // Claude Status (includes network)
    if claude_enabled {
        let proxy_running = state.proxy_health.is_some();
        let claude_reachable = state.usage.error.is_none() && state.usage.fetched_at.is_some();
        let util = state.usage.five_hour.utilization;
        let current_pct = if util > 1.0 { util } else { util * 100.0 };
        let pace = compute_pace(&state.pace_history);
        let eta = compute_eta(current_pct, &state.usage.five_hour.resets_at);
        let (rx_now, tx_now, rx_avg, tx_avg, _, _) = state.system.net_speeds();
        let net = panels::claude_status::NetSpeeds { rx_now, tx_now, rx_avg, tx_avg };
        panels::claude_status::render(
            frame, chunks[idx],
            &state.usage,
            proxy_running,
            claude_reachable,
            pace,
            &eta,
            &net,
            state.last_proxy_ts,
        );
        idx += 1;
    }

    // CPU + Temps side by side
    let cpu_temps_area = chunks[idx];
    idx += 1;
    {
        let halves = Layout::horizontal([
            Constraint::Percentage(50),
            Constraint::Percentage(50),
        ]).split(cpu_temps_area);

        let freq_str = state.lhm_data.as_ref()
            .and_then(|d| d.avg_cpu_freq_ghz_str())
            .unwrap_or_else(|| {
                let mhz = state.system.cpu_freq_mhz();
                if mhz > 0 { format!("{:.2} GHz", mhz as f64 / 1000.0) } else { "? GHz".to_string() }
            });

        panels::cpu::render(
            frame, halves[0],
            state.system.cpu_percent(),
            &freq_str,
            state.system.cpu_avg_5min(),
        );

        // GPU temp for temps panel: prefer LHM, fallback to nvml
        let gpu_temp = state.lhm_data.as_ref()
            .and_then(|d| d.gpu_temp)
            .or_else(|| state.gpu_data.as_ref().map(|g| g.temp_celsius as f32));

        let gpu_temp_max = if state.gpu_temp_max > 0.0 { Some(state.gpu_temp_max) } else { None };
        let gpu_temp_avg = if !state.gpu_temp_samples.is_empty() {
            let sum: f32 = state.gpu_temp_samples.iter().sum();
            Some(sum / state.gpu_temp_samples.len() as f32)
        } else {
            None
        };

        panels::temps::render(frame, halves[1], state.lhm_data.as_ref(), gpu_temp, gpu_temp_max, gpu_temp_avg);
    }

    // Memory + GPU side by side
    let mem_gpu_area = chunks[idx];
    idx += 1;

    if let Some(ref gpu_data) = state.gpu_data {
        let halves = Layout::horizontal([
            Constraint::Percentage(50),
            Constraint::Percentage(50),
        ]).split(mem_gpu_area);
        let (mem_used, mem_total) = state.system.memory_used_total();
        let (swap_used, swap_total) = state.system.swap_used_total();
        panels::memory::render(frame, halves[0], mem_used, mem_total, swap_used, swap_total);
        panels::gpu::render(frame, halves[1], gpu_data);
    } else {
        let (mem_used, mem_total) = state.system.memory_used_total();
        let (swap_used, swap_total) = state.system.swap_used_total();
        panels::memory::render(frame, mem_gpu_area, mem_used, mem_total, swap_used, swap_total);
    }

    // Network (standalone only when Claude panel is disabled — otherwise embedded in Claude panel)
    if !claude_enabled {
        let (rx_now, tx_now, rx_avg, tx_avg, rx_peak, tx_peak) = state.system.net_speeds();
        panels::network::render(frame, chunks[idx], rx_now, tx_now, rx_avg, tx_avg, rx_peak, tx_peak);
        idx += 1;
    }

    // Disks
    let disk_io = state.system.disk_io(&state.disk_active);
    panels::disks::render(frame, chunks[idx], &state.system.disk_usage(), &disk_io);
    idx += 1;

    // Processes
    let (top_cpu, top_mem) = state.system.top_processes(6);
    panels::processes::render(frame, chunks[idx], &top_cpu, &top_mem);
}
