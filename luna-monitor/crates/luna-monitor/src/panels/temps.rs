use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, BorderType, Paragraph};
use ratatui::Frame;

use crate::collectors::lhm::LhmData;
use crate::ui::colors;

pub fn render(
    frame: &mut Frame,
    area: Rect,
    lhm: Option<&LhmData>,
    gpu_temp: Option<f32>,
    gpu_temp_max: Option<f32>,
    gpu_temp_avg: Option<f32>,
) {
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

    // Line 1: CPU temp with ▲max ~avg
    if let Some(lhm) = lhm {
        if let Some(pkg) = lhm.cpu_package_temp {
            let color = colors::temp_color(pkg as f64);
            let mut spans = vec![
                Span::raw("CPU: "),
                Span::styled(format!("{:.0}°C", pkg), Style::default().fg(color)),
            ];
            if inner.width >= 30 {
                if let Some(max) = lhm.cpu_max_temp {
                    spans.push(Span::styled(format!("  ▲{:.0}", max), Style::default().fg(Color::DarkGray)));
                }
                if let Some(avg) = lhm.cpu_avg_temp {
                    spans.push(Span::styled(format!("  ~{:.0}", avg), Style::default().fg(Color::DarkGray)));
                }
            }
            lines.push(Line::from(spans));
        } else {
            lines.push(Line::from(Span::raw("CPU: --")));
        }
    } else {
        lines.push(Line::from(Span::styled(
            "No sensors (install LHM)",
            Style::default().fg(Color::DarkGray),
        )));
    }

    // Line 2: GPU temp with ▲max ~avg
    if let Some(temp) = gpu_temp {
        if temp > 0.0 {
            let color = colors::temp_color(temp as f64);
            let mut spans = vec![
                Span::raw("GPU: "),
                Span::styled(format!("{:.0}°C", temp), Style::default().fg(color)),
            ];
            if inner.width >= 30 {
                if let Some(max) = gpu_temp_max {
                    spans.push(Span::styled(format!("  ▲{:.0}", max), Style::default().fg(Color::DarkGray)));
                }
                if let Some(avg) = gpu_temp_avg {
                    spans.push(Span::styled(format!("  ~{:.0}", avg), Style::default().fg(Color::DarkGray)));
                }
            }
            lines.push(Line::from(spans));
        } else {
            lines.push(Line::from(Span::raw("GPU: --")));
        }
    } else {
        lines.push(Line::from(Span::raw("GPU: --")));
    }

    let paragraph = Paragraph::new(lines);
    frame.render_widget(paragraph, inner);
}
