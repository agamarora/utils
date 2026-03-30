use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::text::Line;
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::collectors::gpu::GpuData;
use crate::ui::{charts, colors};

pub fn render(frame: &mut Frame, area: Rect, gpu: &GpuData) {
    let title = format!(" GPU: {} ({}°C) ", gpu.name, gpu.temp_celsius);

    let block = Block::default()
        .title(title)
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(colors::SYSTEM_BORDER));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 2 || inner.height < 1 {
        return;
    }

    let bar_width = inner.width.saturating_sub(2);
    let util_pct = gpu.utilization_pct as f64;
    let vram_pct = if gpu.vram_total_mb > 0 {
        (gpu.vram_used_mb as f64 / gpu.vram_total_mb as f64) * 100.0
    } else {
        0.0
    };

    let lines = vec![
        Line::from(format!("Util: {}%", gpu.utilization_pct)),
        charts::hbar(util_pct, bar_width),
        Line::from(format!("VRAM: {} / {} MB", gpu.vram_used_mb, gpu.vram_total_mb)),
        charts::hbar(vram_pct, bar_width),
    ];

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
