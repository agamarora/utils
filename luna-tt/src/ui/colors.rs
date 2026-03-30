use ratatui::style::Color;

/// Border color for system panels
pub const SYSTEM_BORDER: Color = Color::Rgb(80, 80, 120);
/// Border color for Claude panels
pub const CLAUDE_BORDER: Color = Color::Rgb(120, 80, 200);

/// Convert HSV (h: 0-360, s: 0-1, v: 0-1) to ratatui Color::Rgb.
/// Pure math, no external crate.
pub fn hsv_to_rgb(h: f64, s: f64, v: f64) -> Color {
    let h = ((h % 360.0) + 360.0) % 360.0;
    let s = s.clamp(0.0, 1.0);
    let v = v.clamp(0.0, 1.0);

    let c = v * s;
    let hp = h / 60.0;
    let x = c * (1.0 - (hp % 2.0 - 1.0).abs());
    let m = v - c;

    let (r1, g1, b1) = if hp < 1.0 {
        (c, x, 0.0)
    } else if hp < 2.0 {
        (x, c, 0.0)
    } else if hp < 3.0 {
        (0.0, c, x)
    } else if hp < 4.0 {
        (0.0, x, c)
    } else if hp < 5.0 {
        (x, 0.0, c)
    } else {
        (c, 0.0, x)
    };

    let r = ((r1 + m) * 255.0).round() as u8;
    let g = ((g1 + m) * 255.0).round() as u8;
    let b = ((b1 + m) * 255.0).round() as u8;

    Color::Rgb(r, g, b)
}

/// Map a percentage (0-100) to a color: green at 0, yellow around 50, red at 100.
pub fn pct_color(pct: f64) -> Color {
    // Hue: 120 (green) -> 60 (yellow) -> 0 (red)
    let hue = 120.0 * (1.0 - (pct / 100.0).clamp(0.0, 1.0));
    hsv_to_rgb(hue, 0.85, 0.9)
}
