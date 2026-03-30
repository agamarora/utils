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
    // Pace tracking: last 3 utilization readings
    pub pace_history: Vec<f64>,
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
    };

    // Prime CPU counters
    state.system.tick();
    std::thread::sleep(Duration::from_secs(1));

    let mut usage_rx = usage_rx;
    let tick_ms = config.tick_ms();

    loop {
        // Check for new usage data from background
        if let Some(ref mut rx) = usage_rx {
            while let Ok(data) = rx.try_recv() {
                // Track pace
                let pct = data.five_hour.utilization * 100.0;
                state.pace_history.push(pct);
                if state.pace_history.len() > 3 {
                    state.pace_history.remove(0);
                }
                state.usage = data;
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
                }
            }
        }

        if let Some(entry) = state.rate_limit_collector.collect() {
            if state.rate_limit_collector.is_fresh() && state.usage.source != "api" {
                if let Some(util) = entry.five_h_utilization {
                    // Track pace from proxy data too
                    let pct = util * 100.0;
                    state.pace_history.push(pct);
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
            let min_height = if config.claude_enabled { 32 } else { 27 };
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

/// Compute pace string from last 3 utilization readings.
fn compute_pace(history: &[f64]) -> &'static str {
    if history.len() < 2 {
        return "";
    }
    let last = *history.last().unwrap();
    let prev = history[history.len() - 2];
    let delta = last - prev;
    if delta > 2.0 {
        "↑ rising"
    } else if delta < -2.0 {
        "↓ falling"
    } else {
        "→ steady"
    }
}

fn render(frame: &mut ratatui::Frame, area: Rect, state: &AppState, config: &Config) {
    let mut constraints = Vec::new();
    let claude_enabled = config.claude_enabled;
    let has_gpu = state.gpu_data.is_some();

    if claude_enabled {
        constraints.push(Constraint::Length(8));  // Claude Status
        constraints.push(Constraint::Length(5));  // CPU + Temps (side by side)
        constraints.push(Constraint::Length(if has_gpu { 5 } else { 5 }));  // Memory (+GPU)
        constraints.push(Constraint::Length(3));  // Network (compact)
        constraints.push(Constraint::Length(6));  // Disks
        constraints.push(Constraint::Min(5));     // Processes
    } else {
        constraints.push(Constraint::Length(5));  // CPU + Temps (side by side)
        constraints.push(Constraint::Length(if has_gpu { 5 } else { 5 }));  // Memory (+GPU)
        constraints.push(Constraint::Length(3));  // Network (compact)
        constraints.push(Constraint::Length(6));  // Disks
        constraints.push(Constraint::Min(8));     // Processes
    }

    let chunks = Layout::vertical(constraints).split(area);
    let mut idx = 0;

    // Claude Status
    if claude_enabled {
        let proxy_running = state.proxy_health.is_some();
        let pace = compute_pace(&state.pace_history);
        panels::claude_status::render(
            frame, chunks[idx],
            &state.usage,
            state.proxy_health.as_ref(),
            proxy_running,
            pace,
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

        panels::temps::render(frame, halves[1], state.lhm_data.as_ref(), gpu_temp);
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

    // Network (compact)
    let (rx_now, tx_now, rx_avg, tx_avg, rx_peak, tx_peak) = state.system.net_speeds();
    panels::network::render(frame, chunks[idx], rx_now, tx_now, rx_avg, tx_avg, rx_peak, tx_peak);
    idx += 1;

    // Disks
    let disk_io = state.system.disk_io(&state.disk_active);
    panels::disks::render(frame, chunks[idx], &state.system.disk_usage(), &disk_io);
    idx += 1;

    // Processes
    let (top_cpu, top_mem) = state.system.top_processes(6);
    panels::processes::render(frame, chunks[idx], &top_cpu, &top_mem);
}
