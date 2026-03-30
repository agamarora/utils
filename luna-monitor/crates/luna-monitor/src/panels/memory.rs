use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::text::Line;
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::ui::{charts, colors};

pub fn render(frame: &mut Frame, area: Rect, mem_used: u64, mem_total: u64, swap_used: u64, swap_total: u64) {
    let mem_pct = if mem_total > 0 { (mem_used as f64 / mem_total as f64) * 100.0 } else { 0.0 };
    let border_color = colors::pct_color(mem_pct);

    let block = Block::default()
        .title(" Memory ")
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(border_color));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 2 || inner.height < 1 {
        return;
    }

    let mem_used_gb = mem_used as f64 / (1024.0 * 1024.0 * 1024.0);
    let mem_total_gb = mem_total as f64 / (1024.0 * 1024.0 * 1024.0);

    let bar_width = inner.width.saturating_sub(2);

    // RAM line, Swap line, then bar for RAM
    let mut lines = vec![
        Line::from(format!("RAM: {:.1} / {:.1} GB ({:.0}%)", mem_used_gb, mem_total_gb, mem_pct)),
    ];

    if swap_total > 0 {
        let swap_used_gb = swap_used as f64 / (1024.0 * 1024.0 * 1024.0);
        let swap_total_gb = swap_total as f64 / (1024.0 * 1024.0 * 1024.0);
        let swap_pct = (swap_used as f64 / swap_total as f64) * 100.0;
        lines.push(Line::from(format!("Swap: {:.1} / {:.1} GB ({:.0}%)", swap_used_gb, swap_total_gb, swap_pct)));
    }

    lines.push(charts::hbar(mem_pct, bar_width));

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
