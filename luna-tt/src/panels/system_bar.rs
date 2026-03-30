use ratatui::Frame;
use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph};
use crate::ui::charts::hbar;
use crate::ui::colors::{pct_color, SYSTEM_BORDER};

/// Render a compact system bar with CPU, RAM, and Disk Active % in 3 rows.
pub fn render(frame: &mut Frame, area: Rect, cpu: f64, ram: f64, disk: f64) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(SYSTEM_BORDER))
        .title(" System ");

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.height < 3 || inner.width < 10 {
        return;
    }

    let bar_width = inner.width.saturating_sub(14).max(5);

    let cpu_pct = cpu.clamp(0.0, 100.0);
    let ram_pct = ram.clamp(0.0, 100.0);
    let disk_pct = disk.clamp(0.0, 100.0);

    let lines = vec![
        Line::from(vec![
            Span::styled("CPU  ", Style::default().fg(ratatui::style::Color::DarkGray)),
            hbar(bar_width, cpu_pct, pct_color(cpu_pct)),
            Span::raw(" "),
            Span::styled(format!("{:5.1}%", cpu_pct), Style::default().fg(pct_color(cpu_pct))),
        ]),
        Line::from(vec![
            Span::styled("RAM  ", Style::default().fg(ratatui::style::Color::DarkGray)),
            hbar(bar_width, ram_pct, pct_color(ram_pct)),
            Span::raw(" "),
            Span::styled(format!("{:5.1}%", ram_pct), Style::default().fg(pct_color(ram_pct))),
        ]),
        Line::from(vec![
            Span::styled("DISK ", Style::default().fg(ratatui::style::Color::DarkGray)),
            hbar(bar_width, disk_pct, pct_color(disk_pct)),
            Span::raw(" "),
            Span::styled(format!("{:5.1}%", disk_pct), Style::default().fg(pct_color(disk_pct))),
        ]),
    ];

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
