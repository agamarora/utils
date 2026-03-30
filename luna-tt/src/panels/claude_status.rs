use ratatui::Frame;
use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph};
use crate::types::UsageData;
use crate::ui::charts::hbar;
use crate::ui::colors::{pct_color, CLAUDE_BORDER};

/// Render the Claude Status panel: 5h/7d utilization bars, ETA, source indicator.
/// Compact: fits in 5 rows.
pub fn render(frame: &mut Frame, area: Rect, usage: &UsageData, _last_proxy_ts: Option<f64>) {
    let block = Block::default()
        .borders(Borders::TOP | Borders::LEFT | Borders::RIGHT | Borders::BOTTOM)
        .border_style(Style::default().fg(CLAUDE_BORDER))
        .title(" Claude ");

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.height < 3 || inner.width < 10 {
        return;
    }

    let bar_width = inner.width.saturating_sub(14).max(5);

    let five_h_pct = (usage.five_hour_utilization * 100.0).clamp(0.0, 100.0);
    let seven_d_pct = (usage.seven_day_utilization * 100.0).clamp(0.0, 100.0);

    let five_h_color = pct_color(five_h_pct);
    let seven_d_color = pct_color(seven_d_pct);

    // Source indicator
    let source_dot = if usage.source == "proxy" {
        Span::styled("P\u{25CF}", Style::default().fg(Color::Green))
    } else {
        Span::styled("P\u{25CB}", Style::default().fg(Color::DarkGray))
    };

    // Status
    let status_style = if usage.status == "rate_limited" {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::DarkGray)
    };

    let lines = vec![
        Line::from(vec![
            Span::styled("5h  ", Style::default().fg(Color::DarkGray)),
            hbar(bar_width, five_h_pct, five_h_color),
            Span::raw(" "),
            Span::styled(format!("{:5.1}%", five_h_pct), Style::default().fg(five_h_color)),
        ]),
        Line::from(vec![
            Span::styled("7d  ", Style::default().fg(Color::DarkGray)),
            hbar(bar_width, seven_d_pct, seven_d_color),
            Span::raw(" "),
            Span::styled(format!("{:5.1}%", seven_d_pct), Style::default().fg(seven_d_color)),
        ]),
        Line::from(vec![
            Span::styled("ETA ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                if usage.five_hour_reset.is_empty() { "-".to_string() } else { usage.five_hour_reset.clone() },
                Style::default().fg(Color::DarkGray),
            ),
            Span::raw("  "),
            source_dot,
            Span::raw(" "),
            Span::styled(&usage.status, status_style),
        ]),
    ];

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
