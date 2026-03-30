use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use luna_common::types::{ProxyHealth, UsageData};
use crate::ui::{charts, colors};

pub fn render(
    frame: &mut Frame,
    area: Rect,
    usage: &UsageData,
    proxy_health: Option<&ProxyHealth>,
    proxy_running: bool,
    pace: &str,
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

    // 5h utilization with pace indicator
    let five_h_pct = usage.five_hour.utilization * 100.0;
    let five_h_reset = format_reset(&usage.five_hour.resets_at);
    let pace_str = if !pace.is_empty() { format!(" {}", pace) } else { String::new() };
    lines.push(Line::from(format!("5h: {:.1}%{} {}", five_h_pct, pace_str, five_h_reset)));
    lines.push(charts::hbar(five_h_pct, bar_width));

    // 7d utilization
    let seven_d_pct = usage.seven_day.utilization * 100.0;
    let seven_d_reset = format_reset(&usage.seven_day.resets_at);
    lines.push(Line::from(format!("7d: {:.1}% {}", seven_d_pct, seven_d_reset)));
    lines.push(charts::hbar(seven_d_pct, bar_width));

    // Source + proxy health on one line
    let mut source_parts = Vec::new();
    if proxy_running {
        source_parts.push(Span::styled("via proxy", Style::default().fg(Color::Green)));
        if let Some(health) = proxy_health {
            source_parts.push(Span::styled(
                format!("  {}ms  {} reqs  {} 429s",
                    health.last_latency_ms as u64,
                    health.requests_proxied,
                    health.api_errors_429),
                Style::default().fg(Color::DarkGray),
            ));
        }
    } else {
        source_parts.push(Span::styled("via API", Style::default().fg(Color::DarkGray)));
    }
    lines.push(Line::from(source_parts));

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
