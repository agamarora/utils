use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::ui::{charts, colors};

pub fn render(
    frame: &mut Frame,
    area: Rect,
    rx_now: f64, tx_now: f64,
    rx_avg: f64, tx_avg: f64,
    rx_peak: f64, tx_peak: f64,
) {
    let block = Block::default()
        .title(" Network ")
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(colors::SYSTEM_BORDER));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 2 || inner.height < 1 {
        return;
    }

    let lines = vec![
        Line::from(vec![
            Span::styled("↓ ", Style::default().fg(Color::Green)),
            Span::raw(format!("{} / avg {} / peak {}",
                charts::fmt_speed(rx_now),
                charts::fmt_speed(rx_avg),
                charts::fmt_speed(rx_peak))),
        ]),
        Line::from(vec![
            Span::styled("↑ ", Style::default().fg(Color::Red)),
            Span::raw(format!("{} / avg {} / peak {}",
                charts::fmt_speed(tx_now),
                charts::fmt_speed(tx_avg),
                charts::fmt_speed(tx_peak))),
        ]),
    ];

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
