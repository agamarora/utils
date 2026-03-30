use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::collectors::system::{DiskInfo, DiskIO};
use crate::ui::{charts, colors};

pub fn render(frame: &mut Frame, area: Rect, usage: &[DiskInfo], io: &[DiskIO]) {
    // Border color: max active % across all drives
    let max_active = io.iter().map(|d| d.active_pct).fold(0.0f64, f64::max);
    let border_color = if max_active > 1.0 {
        colors::pct_color(max_active)
    } else {
        colors::SYSTEM_BORDER
    };

    let block = Block::default()
        .title(" Disks ")
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(border_color));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 2 || inner.height < 1 {
        return;
    }

    // Sort drives alphabetically by mount point
    let mut sorted_usage: Vec<&DiskInfo> = usage.iter().collect();
    sorted_usage.sort_by(|a, b| a.mount.cmp(&b.mount));

    let mut lines = Vec::new();
    let bar_width = inner.width.saturating_sub(2);

    for disk in sorted_usage {
        let label = if disk.mount.len() <= 3 {
            disk.mount.clone()
        } else {
            disk.name.clone()
        };

        // Find matching IO data
        let io_data = io.iter().find(|d| d.name == disk.mount || d.name == disk.name);
        let active_pct = io_data.map(|d| d.active_pct).unwrap_or(0.0);

        // Bar shows active % when available, otherwise capacity %
        let bar_pct = if active_pct > 0.0 { active_pct } else { disk.pct };

        // Split into separate spans: active% colored, capacity in neutral color
        let has_pdh = io_data.is_some();
        let mut spans = Vec::new();
        spans.push(Span::raw(format!("{} ", label)));

        if has_pdh {
            spans.push(Span::styled(
                format!("{:.0}% active", active_pct),
                Style::default().fg(colors::pct_color(active_pct)),
            ));
            spans.push(Span::raw("  "));
        }

        spans.push(Span::styled(
            format!("{:.0}/{:.0} GB ({:.0}%)", disk.used_gb, disk.total_gb, disk.pct),
            Style::default().fg(Color::DarkGray),
        ));

        lines.push(Line::from(spans));
        lines.push(charts::hbar(bar_pct, bar_width));
    }

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
