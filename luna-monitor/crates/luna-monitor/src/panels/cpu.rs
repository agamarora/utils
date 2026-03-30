use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::ui::{charts, colors};

pub fn render(frame: &mut Frame, area: Rect, cpu_pct: f32, freq_str: &str, avg_5min: Option<f32>) {
    let border_color = colors::pct_color(cpu_pct as f64);

    let block = Block::default()
        .title(" CPU ")
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(border_color));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 2 || inner.height < 1 {
        return;
    }

    // Line 1: current %, avg %, frequency
    let avg_str = match avg_5min {
        Some(avg) if inner.width >= 30 => format!("  avg {:.1}%", avg),
        _ => String::new(),
    };
    let info_line = Line::from(vec![
        Span::styled(format!("{:.1}%", cpu_pct), Style::default().fg(colors::pct_color(cpu_pct as f64))),
        Span::raw(format!("{}  @ {}", avg_str, freq_str)),
    ]);

    // Line 2: hbar
    let bar = charts::hbar(cpu_pct as f64, inner.width);

    let paragraph = Paragraph::new(vec![info_line, bar]);
    frame.render_widget(paragraph, inner);
}
