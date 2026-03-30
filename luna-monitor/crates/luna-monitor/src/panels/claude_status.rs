use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use luna_common::types::UsageData;
use crate::ui::{charts, colors};

pub struct NetSpeeds {
    pub rx_now: f64,
    pub tx_now: f64,
    pub rx_avg: f64,
    pub tx_avg: f64,
}

pub fn render(
    frame: &mut Frame,
    area: Rect,
    usage: &UsageData,
    proxy_running: bool,
    claude_reachable: bool,
    pace: &str,
    eta: &str,
    net: &NetSpeeds,
) {
    let title = if usage.plan_name.is_empty() {
        " Claude Usage ".to_string()
    } else {
        format!(" Claude Usage ({}) ", usage.plan_name)
    };

    let block = Block::default()
        .title(title)
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(colors::CLAUDE_BORDER));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 10 || inner.height < 1 {
        return;
    }

    let bar_width = inner.width.saturating_sub(2);
    let mut lines = Vec::new();

    // Check for error state
    if let Some(ref err) = usage.error {
        if err.contains("No credentials") {
            lines.push(Line::from(Span::styled(
                "Getting Started: Run 'claude' to authenticate",
                Style::default().fg(Color::Yellow),
            )));
            let paragraph = Paragraph::new(lines);
            frame.render_widget(paragraph, inner);
            return;
        }
        lines.push(Line::from(Span::styled(
            format!("Error: {}", err),
            Style::default().fg(Color::Red),
        )));
    }

    // 5h utilization (API may return 0-1 or 0-100)
    let five_h_pct = as_pct(usage.five_hour.utilization);
    let five_h_reset = format_reset(&usage.five_hour.resets_at);
    lines.push(Line::from(format!("5h: {:.1}% {}", five_h_pct, five_h_reset)));
    lines.push(charts::hbar(five_h_pct, bar_width));

    // 7d utilization
    let seven_d_pct = as_pct(usage.seven_day.utilization);
    let seven_d_reset = format_reset(&usage.seven_day.resets_at);
    lines.push(Line::from(format!("7d: {:.1}% {}", seven_d_pct, seven_d_reset)));
    lines.push(charts::hbar(seven_d_pct, bar_width));

    // Network line
    lines.push(Line::from(vec![
        Span::styled("Net ", Style::default().fg(Color::DarkGray)),
        Span::styled("↓", Style::default().fg(Color::Green)),
        Span::raw(format!("{} ", charts::fmt_speed(net.rx_now))),
        Span::styled("↑", Style::default().fg(Color::Red)),
        Span::raw(format!("{}", charts::fmt_speed(net.tx_now))),
        Span::styled(
            format!("  avg ↓{} ↑{}", charts::fmt_speed(net.rx_avg), charts::fmt_speed(net.tx_avg)),
            Style::default().fg(Color::DarkGray),
        ),
    ]));

    // Status dots + pace + ETA
    let mut parts = Vec::new();

    // P● proxy status
    let (p_dot, p_color) = if proxy_running { ("P●", Color::Green) } else { ("P●", Color::Red) };
    parts.push(Span::styled(p_dot, Style::default().fg(p_color)));
    parts.push(Span::raw(" "));

    // C● claude reachable
    let (c_dot, c_color) = if claude_reachable { ("C●", Color::Green) } else { ("C●", Color::Red) };
    parts.push(Span::styled(c_dot, Style::default().fg(c_color)));

    if !pace.is_empty() {
        parts.push(Span::styled(" · ", Style::default().fg(Color::DarkGray)));
        let pace_color = if pace.starts_with('↑') {
            Color::Yellow
        } else if pace.starts_with('↓') {
            Color::Cyan
        } else {
            Color::DarkGray
        };
        parts.push(Span::styled(pace, Style::default().fg(pace_color)));
    }
    if !eta.is_empty() {
        parts.push(Span::styled(" · ", Style::default().fg(Color::DarkGray)));
        parts.push(Span::styled(eta, Style::default().fg(Color::DarkGray)));
    }
    lines.push(Line::from(parts));

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}

fn format_reset(resets_at: &str) -> String {
    if resets_at.is_empty() {
        return String::new();
    }

    // Try as epoch
    if let Ok(epoch) = resets_at.parse::<f64>() {
        if epoch > 1_000_000_000.0 {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs_f64();
            let remaining = epoch - now;
            if remaining > 0.0 {
                return format_duration(remaining);
            }
            return "(reset)".to_string();
        }
    }

    // Try as ISO 8601
    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(resets_at) {
        let now = chrono::Utc::now();
        let remaining = dt.signed_duration_since(now);
        if remaining.num_seconds() > 0 {
            return format_duration(remaining.num_seconds() as f64);
        }
        return "(reset)".to_string();
    }

    // Try UTC format without timezone
    if let Ok(dt) = chrono::NaiveDateTime::parse_from_str(resets_at, "%Y-%m-%dT%H:%M:%SZ") {
        let now = chrono::Utc::now().naive_utc();
        let remaining = dt.signed_duration_since(now);
        if remaining.num_seconds() > 0 {
            return format_duration(remaining.num_seconds() as f64);
        }
        return "(reset)".to_string();
    }

    String::new()
}

/// Normalize utilization to 0-100 percentage.
/// API may return 0-1 (fraction) or 0-100 (already percentage).
fn as_pct(v: f64) -> f64 {
    if v > 1.0 { v } else { v * 100.0 }
}

fn format_duration(seconds: f64) -> String {
    let total_min = (seconds / 60.0).max(0.0) as u64;
    if total_min >= 1440 {
        // >= 24 hours: show days + hours
        let days = total_min / 1440;
        let hours = (total_min % 1440) / 60;
        format!("(resets in {}d {}h)", days, hours)
    } else if total_min >= 60 {
        // >= 1 hour: show hours + minutes
        let hours = total_min / 60;
        let mins = total_min % 60;
        format!("(resets in {}h {}m)", hours, mins)
    } else {
        // < 1 hour: show minutes
        format!("(resets in {}m)", total_min)
    }
}
