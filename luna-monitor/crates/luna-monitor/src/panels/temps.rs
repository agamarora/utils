use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::collectors::lhm::LhmData;
use crate::ui::colors;

pub fn render(frame: &mut Frame, area: Rect, lhm: Option<&LhmData>, gpu_temp: Option<f32>) {
    let border_color = lhm
        .and_then(|d| d.cpu_package_temp)
        .map(|t| colors::temp_color(t as f64))
        .unwrap_or(colors::SYSTEM_BORDER);

    let block = Block::default()
        .title(" Temps ")
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(border_color));

    let inner = block.inner(area);
    frame.render_widget(block, area);

    if inner.width < 2 || inner.height < 1 {
        return;
    }

    let mut lines = Vec::new();

    // Line 1: CPU temp
    if let Some(lhm) = lhm {
        if let Some(pkg) = lhm.cpu_package_temp {
            let color = colors::temp_color(pkg as f64);
            if inner.width >= 30 {
                // Full: CPU: 45°C (max 52, avg 38)
                let max_str = lhm.cpu_max_temp
                    .map(|t| format!("max {:.0}", t))
                    .unwrap_or_else(|| "--".to_string());
                let avg_str = lhm.cpu_avg_temp
                    .map(|t| format!("avg {:.0}", t))
                    .unwrap_or_else(|| "--".to_string());
                lines.push(Line::from(vec![
                    Span::raw("CPU: "),
                    Span::styled(format!("{:.0}°C", pkg), Style::default().fg(color)),
                    Span::raw(format!(" ({}, {})", max_str, avg_str)),
                ]));
            } else {
                // Narrow: CPU: 45°C
                lines.push(Line::from(vec![
                    Span::raw("CPU: "),
                    Span::styled(format!("{:.0}°C", pkg), Style::default().fg(color)),
                ]));
            }
        } else {
            lines.push(Line::from(Span::raw("CPU: --")));
        }
    } else {
        lines.push(Line::from(Span::styled(
            "No sensors (install LHM)",
            Style::default().fg(Color::DarkGray),
        )));
    }

    // Line 2: GPU temp
    if let Some(temp) = gpu_temp {
        if temp > 0.0 {
            let color = colors::temp_color(temp as f64);
            lines.push(Line::from(vec![
                Span::raw("GPU: "),
                Span::styled(format!("{:.0}°C", temp), Style::default().fg(color)),
            ]));
        } else {
            lines.push(Line::from(Span::raw("GPU: --")));
        }
    } else {
        lines.push(Line::from(Span::raw("GPU: --")));
    }

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
