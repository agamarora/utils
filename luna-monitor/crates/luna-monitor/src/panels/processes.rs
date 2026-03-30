use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::collectors::system::ProcessInfo;
use crate::ui::colors;

pub fn render(frame: &mut Frame, area: Rect, top_cpu: &[ProcessInfo], top_mem: &[ProcessInfo]) {
    let block = Block::default()
        .title(" Processes ")
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(colors::SYSTEM_BORDER));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 10 || inner.height < 2 {
        return;
    }

    // Split into two columns
    let chunks = Layout::horizontal([
        Constraint::Percentage(50),
        Constraint::Percentage(50),
    ]).split(inner);

    // CPU column
    render_column(frame, chunks[0], "Top CPU", top_cpu, |p| format!("{:.1}%", p.cpu_pct));

    // Memory column
    render_column(frame, chunks[1], "Top Memory", top_mem, |p| format!("{:.0} MB", p.mem_mb));
}

fn render_column(frame: &mut Frame, area: Rect, header: &str, procs: &[ProcessInfo], value_fn: impl Fn(&ProcessInfo) -> String) {
    let mut lines = vec![
        Line::from(Span::styled(
            format!("  PID  Name            {}", header.split_whitespace().last().unwrap_or("")),
            Style::default().fg(Color::DarkGray),
        )),
    ];

    for proc in procs.iter().take(6) {
        let name = if proc.name.len() > 15 {
            format!("{}…", &proc.name[..14])
        } else {
            format!("{:<15}", proc.name)
        };
        let color = if proc.is_claude { Color::Cyan } else { Color::White };
        lines.push(Line::from(vec![
            Span::styled(
                format!("{:>5} {} {}", proc.pid, name, value_fn(proc)),
                Style::default().fg(color),
            ),
        ]));
    }

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, area);
}
