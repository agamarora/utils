use ratatui::Frame;
use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph};
use crate::ui::colors::SYSTEM_BORDER;

/// Render top processes by CPU in a compact single-column list.
pub fn render(frame: &mut Frame, area: Rect, procs: &[(u32, String, f32)]) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(SYSTEM_BORDER))
        .title(" Top CPU ");

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.height < 1 || inner.width < 10 {
        return;
    }

    let max_name_len = (inner.width as usize).saturating_sub(12);

    let lines: Vec<Line> = procs.iter()
        .take(inner.height as usize)
        .map(|(pid, name, cpu)| {
            let truncated_name = if name.len() > max_name_len {
                &name[..max_name_len]
            } else {
                name.as_str()
            };

            let cpu_color = if *cpu > 80.0 {
                Color::Red
            } else if *cpu > 40.0 {
                Color::Yellow
            } else {
                Color::DarkGray
            };

            Line::from(vec![
                Span::styled(
                    format!("{:>5} ", pid),
                    Style::default().fg(Color::DarkGray),
                ),
                Span::styled(
                    format!("{:<width$}", truncated_name, width = max_name_len),
                    Style::default().fg(Color::Gray),
                ),
                Span::styled(
                    format!("{:5.1}%", cpu),
                    Style::default().fg(cpu_color),
                ),
            ])
        })
        .collect();

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
