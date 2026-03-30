use ratatui::layout::Rect;
use ratatui::style::Style;
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;
use std::collections::VecDeque;

use crate::ui::{charts, colors};

const SPARK_CHARS: &[char] = &['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

pub fn render(frame: &mut Frame, area: Rect, cpu_pct: f32, freq_str: &str, history: &VecDeque<f32>) {
    // Build sparkline from last 20 history points
    let spark = sparkline(history, 20);
    let title = format!(" CPU: {:.1}% @ {} {} ", cpu_pct, freq_str, spark);

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

    let bar = charts::hbar(cpu_pct as f64, inner.width);
    let paragraph = Paragraph::new(vec![bar]);
    frame.render_widget(paragraph, inner);
}

fn sparkline(history: &VecDeque<f32>, width: usize) -> String {
    if history.is_empty() {
        return String::new();
    }
    let start = if history.len() > width { history.len() - width } else { 0 };
    history.iter()
        .skip(start)
        .map(|&v| {
            let idx = ((v.clamp(0.0, 100.0) / 100.0) * 7.0) as usize;
            SPARK_CHARS[idx.min(7)]
        })
        .collect()
}
