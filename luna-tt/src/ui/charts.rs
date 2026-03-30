use ratatui::style::{Color, Style};
use ratatui::text::Span;

/// Unicode block characters for horizontal bars, from empty to full (8 levels).
const BLOCKS: [char; 8] = [' ', '\u{2581}', '\u{2582}', '\u{2583}', '\u{2584}', '\u{2585}', '\u{2586}', '\u{2587}'];
const FULL_BLOCK: char = '\u{2588}';

/// Render a horizontal bar of `width` characters representing `pct` (0-100).
pub fn hbar(width: u16, pct: f64, color: Color) -> Span<'static> {
    let pct = pct.clamp(0.0, 100.0);
    let filled_f = (pct / 100.0) * width as f64;
    let full_cells = filled_f as usize;
    let remainder = filled_f - full_cells as f64;
    let partial_idx = (remainder * 8.0) as usize;

    let mut bar = String::with_capacity(width as usize);
    for _ in 0..full_cells.min(width as usize) {
        bar.push(FULL_BLOCK);
    }
    if full_cells < width as usize && partial_idx > 0 {
        bar.push(BLOCKS[partial_idx.min(7)]);
    }
    // Pad remaining
    while bar.chars().count() < width as usize {
        bar.push(' ');
    }

    Span::styled(bar, Style::default().fg(color))
}

/// Format bytes into human-readable string (B, KB, MB, GB, TB).
pub fn fmt_bytes(bytes: u64) -> String {
    const UNITS: &[&str] = &["B", "KB", "MB", "GB", "TB"];
    let mut val = bytes as f64;
    for unit in UNITS {
        if val < 1024.0 {
            return if val < 10.0 {
                format!("{:.1}{}", val, unit)
            } else {
                format!("{:.0}{}", val, unit)
            };
        }
        val /= 1024.0;
    }
    format!("{:.0}PB", val)
}

/// Format bytes/sec into human-readable speed string.
pub fn fmt_speed(bytes_per_sec: f64) -> String {
    if bytes_per_sec < 1024.0 {
        format!("{:.0} B/s", bytes_per_sec)
    } else if bytes_per_sec < 1024.0 * 1024.0 {
        format!("{:.1} KB/s", bytes_per_sec / 1024.0)
    } else if bytes_per_sec < 1024.0 * 1024.0 * 1024.0 {
        format!("{:.1} MB/s", bytes_per_sec / (1024.0 * 1024.0))
    } else {
        format!("{:.1} GB/s", bytes_per_sec / (1024.0 * 1024.0 * 1024.0))
    }
}
