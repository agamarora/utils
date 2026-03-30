use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::collectors::system::{DiskInfo, DiskIO};
use crate::ui::{charts, colors};

pub fn render(frame: &mut Frame, area: Rect, usage: &[DiskInfo], io: &[DiskIO]) {
    let block = Block::default()
        .title(" Disks ")
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(colors::SYSTEM_BORDER));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 2 || inner.height < 1 {
        return;
    }

    let mut lines = Vec::new();
    let bar_width = inner.width.saturating_sub(2);

    for disk in usage {
        let label = if disk.mount.len() <= 3 {
            disk.mount.clone()
        } else {
            disk.name.clone()
        };

        // Find matching IO data
        let io_data = io.iter().find(|d| d.name == disk.mount || d.name == disk.name);

        if let Some(io) = io_data {
            if io.active_pct > 0.0 || io.read_bps > 0.0 || io.write_bps > 0.0 {
                // I/O mode: show active %, read/write speeds
                lines.push(Line::from(vec![
                    Span::styled(
                        format!("{} {:.0}% active  R:{}/s  W:{}/s",
                            label,
                            io.active_pct,
                            charts::fmt_bytes(io.read_bps as u64),
                            charts::fmt_bytes(io.write_bps as u64)),
                        Style::default().fg(colors::io_color(io.read_bps + io.write_bps)),
                    ),
                ]));
                lines.push(charts::hbar(io.active_pct, bar_width));
                continue;
            }
        }

        // Fallback: capacity mode
        lines.push(Line::from(vec![
            Span::styled(
                format!("{} {:.1}/{:.1} GB ({:.0}%)", label, disk.used_gb, disk.total_gb, disk.pct),
                Style::default().fg(colors::pct_color(disk.pct)),
            ),
        ]));
        lines.push(charts::hbar(disk.pct, bar_width));
    }

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
