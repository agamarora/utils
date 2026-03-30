use ratatui::style::Color;

pub const CLAUDE_BORDER: Color = Color::Cyan;
pub const SYSTEM_BORDER: Color = Color::DarkGray;
pub const BURNDOWN_COLOR: Color = Color::Magenta;
pub const CPU_COLOR: Color = Color::Cyan;

pub fn pct_color(pct: f64) -> Color {
    if pct < 60.0 {
        Color::Cyan
    } else if pct < 85.0 {
        Color::Yellow
    } else {
        Color::Red
    }
}

pub fn temp_color(c: f64) -> Color {
    if c < 70.0 {
        Color::Green
    } else if c < 85.0 {
        Color::Yellow
    } else {
        Color::Red
    }
}

pub fn io_color(bps: f64) -> Color {
    let mb = bps / (1024.0 * 1024.0);
    if mb < 1.0 {
        Color::DarkGray
    } else if mb < 10.0 {
        Color::Cyan
    } else if mb < 100.0 {
        Color::Yellow
    } else {
        Color::Red
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pct_color_ranges() {
        assert_eq!(pct_color(30.0), Color::Cyan);
        assert_eq!(pct_color(59.9), Color::Cyan);
        assert_eq!(pct_color(60.0), Color::Yellow);
        assert_eq!(pct_color(84.9), Color::Yellow);
        assert_eq!(pct_color(85.0), Color::Red);
        assert_eq!(pct_color(100.0), Color::Red);
    }

    #[test]
    fn test_temp_color_ranges() {
        assert_eq!(temp_color(50.0), Color::Green);
        assert_eq!(temp_color(75.0), Color::Yellow);
        assert_eq!(temp_color(90.0), Color::Red);
    }

    #[test]
    fn test_io_color_ranges() {
        assert_eq!(io_color(0.0), Color::DarkGray);
        assert_eq!(io_color(5.0 * 1024.0 * 1024.0), Color::Cyan);
        assert_eq!(io_color(50.0 * 1024.0 * 1024.0), Color::Yellow);
        assert_eq!(io_color(200.0 * 1024.0 * 1024.0), Color::Red);
    }
}
