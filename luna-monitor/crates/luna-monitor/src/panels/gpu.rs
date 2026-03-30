use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::collectors::gpu::GpuData;
use crate::ui::{charts, colors};

pub fn render(frame: &mut Frame, area: Rect, gpu: &GpuData) {
    let border_color = colors::pct_color(gpu.utilization_pct as f64);

    let block = Block::default()
        .title(" GPU ")
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(border_color));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 2 || inner.height < 1 {
        return;
    }

    let bar_width = inner.width.saturating_sub(2);
    let util_pct = gpu.utilization_pct as f64;

    let vram_str = if gpu.vram_total_mb > 0 {
        format!(" ({:.1}/{:.1} GB)",
            gpu.vram_used_mb as f64 / 1024.0,
            gpu.vram_total_mb as f64 / 1024.0)
    } else {
        String::new()
    };

    let lines = vec![
        // Line 1: GPU name
        Line::from(Span::raw(&gpu.name)),
        // Line 2: Util + VRAM combined
        Line::from(format!("Util: {}%{}", gpu.utilization_pct, vram_str)),
        // Line 3: bar
        charts::hbar(util_pct, bar_width),
    ];

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
