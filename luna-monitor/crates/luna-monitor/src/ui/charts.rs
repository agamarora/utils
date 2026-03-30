use std::collections::VecDeque;
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};

const BLOCKS: &[char] = &[' ', '▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

/// Filled area waveform chart using Unicode block characters.
/// Each column maps one history value (0-100) to height rows.
/// Columns fill right-to-left (newest on right).
pub fn wave_chart(history: &VecDeque<f32>, width: u16, height: u16, color: Color) -> Vec<Line<'static>> {
    let w = width as usize;
    let h = height as usize;
    if w == 0 || h == 0 {
        return vec![];
    }

    // Sample last `width` points from history
    let len = history.len();
    let start = if len > w { len - w } else { 0 };
    let values: Vec<f32> = history.iter().skip(start).copied().collect();

    // Build grid top-to-bottom
    let mut lines = Vec::with_capacity(h);
    let total_units = h * 8; // 8 sub-blocks per row

    for row in 0..h {
        let row_from_bottom = h - 1 - row;
        let row_bottom_units = row_from_bottom * 8;

        let mut spans = Vec::with_capacity(w);
        // Pad left if fewer values than width
        let pad = if values.len() < w { w - values.len() } else { 0 };
        for _ in 0..pad {
            spans.push(Span::raw(" "));
        }

        for &val in &values {
            let val_clamped = val.clamp(0.0, 100.0);
            let fill_units = (val_clamped as f64 / 100.0 * total_units as f64) as usize;

            let block_char = if fill_units <= row_bottom_units {
                BLOCKS[0] // empty — value doesn't reach this row
            } else {
                let units_in_row = fill_units - row_bottom_units;
                let idx = units_in_row.min(8);
                BLOCKS[idx]
            };
            spans.push(Span::styled(
                block_char.to_string(),
                Style::default().fg(color),
            ));
        }

        lines.push(Line::from(spans));
    }

    lines
}

/// Horizontal bar gauge: █ filled, ░ empty, colored by percentage.
pub fn hbar(pct: f64, width: u16) -> Line<'static> {
    let w = width as usize;
    if w == 0 {
        return Line::from("");
    }
    let pct_clamped = pct.clamp(0.0, 100.0);
    let filled = ((pct_clamped / 100.0) * w as f64).round() as usize;
    let empty = w.saturating_sub(filled);

    let color = crate::ui::colors::pct_color(pct_clamped);
    let filled_str: String = "█".repeat(filled);
    let empty_str: String = "░".repeat(empty);

    Line::from(vec![
        Span::styled(filled_str, Style::default().fg(color)),
        Span::styled(empty_str, Style::default().fg(Color::DarkGray)),
    ])
}

/// Format byte count: B, KB, MB, GB, TB (1024 base).
pub fn fmt_bytes(bytes: u64) -> String {
    const KB: u64 = 1024;
    const MB: u64 = 1024 * KB;
    const GB: u64 = 1024 * MB;
    const TB: u64 = 1024 * GB;

    if bytes >= TB {
        format!("{:.1} TB", bytes as f64 / TB as f64)
    } else if bytes >= GB {
        format!("{:.1} GB", bytes as f64 / GB as f64)
    } else if bytes >= MB {
        format!("{:.1} MB", bytes as f64 / MB as f64)
    } else if bytes >= KB {
        format!("{:.1} KB", bytes as f64 / KB as f64)
    } else {
        format!("{} B", bytes)
    }
}

/// Format network speed in Mb/s display.
pub fn fmt_speed(mbps: f64) -> String {
    if mbps < 1.0 {
        format!("{:.0} Kb/s", mbps * 1000.0)
    } else if mbps < 1000.0 {
        format!("{:.1} Mb/s", mbps)
    } else {
        format!("{:.1} Gb/s", mbps / 1000.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_wave_chart_normal() {
        let mut history = VecDeque::new();
        for i in 0..300 {
            history.push_back((i % 100) as f32);
        }
        let lines = wave_chart(&history, 80, 10, Color::Cyan);
        assert_eq!(lines.len(), 10);
        // Each line should have spans totaling 80 characters
        for line in &lines {
            let total_chars: usize = line.spans.iter().map(|s| s.content.chars().count()).sum();
            assert_eq!(total_chars, 80);
        }
    }

    #[test]
    fn test_wave_chart_empty() {
        let history = VecDeque::new();
        let lines = wave_chart(&history, 80, 10, Color::Cyan);
        assert_eq!(lines.len(), 10);
        // All spaces (padding)
    }

    #[test]
    fn test_wave_chart_single_point() {
        let mut history = VecDeque::new();
        history.push_back(50.0);
        let lines = wave_chart(&history, 20, 5, Color::Cyan);
        assert_eq!(lines.len(), 5);
    }

    #[test]
    fn test_hbar_0_percent() {
        let line = hbar(0.0, 20);
        let text: String = line.spans.iter().map(|s| s.content.as_ref()).collect();
        assert_eq!(text.chars().filter(|&c| c == '░').count(), 20);
    }

    #[test]
    fn test_hbar_100_percent() {
        let line = hbar(100.0, 20);
        let text: String = line.spans.iter().map(|s| s.content.as_ref()).collect();
        assert_eq!(text.chars().filter(|&c| c == '█').count(), 20);
    }

    #[test]
    fn test_hbar_50_percent() {
        let line = hbar(50.0, 20);
        let text: String = line.spans.iter().map(|s| s.content.as_ref()).collect();
        assert_eq!(text.chars().filter(|&c| c == '█').count(), 10);
        assert_eq!(text.chars().filter(|&c| c == '░').count(), 10);
    }

    #[test]
    fn test_fmt_bytes() {
        assert_eq!(fmt_bytes(0), "0 B");
        assert_eq!(fmt_bytes(1023), "1023 B");
        assert_eq!(fmt_bytes(1024), "1.0 KB");
        assert_eq!(fmt_bytes(1048576), "1.0 MB");
        assert_eq!(fmt_bytes(1073741824), "1.0 GB");
    }

    #[test]
    fn test_fmt_speed() {
        assert_eq!(fmt_speed(0.5), "500 Kb/s");
        assert_eq!(fmt_speed(1.0), "1.0 Mb/s");
        assert_eq!(fmt_speed(100.0), "100.0 Mb/s");
        assert_eq!(fmt_speed(1500.0), "1.5 Gb/s");
    }
}
