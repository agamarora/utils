use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::collectors::gpu::GpuData;
use crate::collectors::lhm::LhmData;
use crate::ui::colors;

pub fn render(frame: &mut Frame, area: Rect, lhm: Option<&LhmData>, gpu: Option<&GpuData>) {
    let block = Block::default()
        .title(" Temperatures ")
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(colors::SYSTEM_BORDER));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 2 || inner.height < 1 {
        return;
    }

    let mut lines = Vec::new();

    // LHM temps
    if let Some(lhm) = lhm {
        for (label, &celsius) in &lhm.temps {
            let color = colors::temp_color(celsius as f64);
            lines.push(Line::from(vec![
                Span::raw(format!("{}: ", label)),
                Span::styled(format!("{:.0}°C", celsius), Style::default().fg(color)),
            ]));
        }
    }

    // GPU temp
    if let Some(gpu) = gpu {
        let color = colors::temp_color(gpu.temp_celsius as f64);
        lines.push(Line::from(vec![
            Span::raw(format!("GPU ({}): ", gpu.name)),
            Span::styled(format!("{}°C", gpu.temp_celsius), Style::default().fg(color)),
        ]));
    }

    if lines.is_empty() {
        lines.push(Line::from(Span::styled(
            "No sensors (install LHM for temps)",
            Style::default().fg(Color::DarkGray),
        )));
    }

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
