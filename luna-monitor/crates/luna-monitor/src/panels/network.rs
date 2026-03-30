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
    _rx_peak: f64, _tx_peak: f64,
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

    // Single compact line: ↓ 1.2 Mb/s  ↑ 5 Kb/s  (avg ↓1.0 ↑3 Mb/s)
    let line = Line::from(vec![
        Span::styled("↓ ", Style::default().fg(Color::Green)),
        Span::raw(charts::fmt_speed(rx_now)),
        Span::raw("  "),
        Span::styled("↑ ", Style::default().fg(Color::Red)),
        Span::raw(charts::fmt_speed(tx_now)),
        Span::raw(format!("  (avg ↓{} ↑{})", charts::fmt_speed(rx_avg), charts::fmt_speed(tx_avg))),
    ]);

    let paragraph = Paragraph::new(vec![line]);
    frame.render_widget(paragraph, inner);
}
