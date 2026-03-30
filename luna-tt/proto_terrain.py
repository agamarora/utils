"""
Prototype: Terrain / Topography (Candidate C)
Usage data mapped to elevation. Time extends left to right.
Color bands show elevation layers. Mountains = intense periods.
"""
import random
import math
import sys

BRAILLE_BASE = 0x2800
DOT_MAP = {
    (0, 0): 0x01, (1, 0): 0x08,
    (0, 1): 0x02, (1, 1): 0x10,
    (0, 2): 0x04, (1, 2): 0x20,
    (0, 3): 0x40, (1, 3): 0x80,
}

COLS = 60
ROWS = 20
PX_W = COLS * 2   # 120
PX_H = ROWS * 4   # 80


def elevation_color(height, max_h):
    """Color based on elevation — deep sea to snow cap."""
    t = height / max(max_h, 1)
    if t < 0.15:
        return (20, 30, 60)       # deep water
    elif t < 0.3:
        return (30, 60, 90)       # shallow water
    elif t < 0.45:
        return (50, 120, 70)      # lowlands
    elif t < 0.6:
        return (80, 160, 60)      # hills
    elif t < 0.75:
        return (140, 130, 60)     # highlands
    elif t < 0.88:
        return (160, 100, 50)     # mountains
    else:
        return (220, 220, 230)    # snow


def generate_terrain(time_periods, seed):
    """
    Generate heightmap from fake usage data.
    Each column = a time slice. Height = intensity.
    Uses layered noise for organic feel.
    """
    rng = random.Random(seed)
    heightmap = [[0.0] * PX_W for _ in range(PX_H)]

    # Generate usage intensity per time column
    intensities = []
    base = 0.3
    for i in range(min(time_periods, PX_W)):
        # Simulate usage: random walks with bursts
        base += rng.gauss(0, 0.05)
        base = max(0.1, min(0.9, base))
        # Occasional bursts (heavy sessions)
        if rng.random() < 0.1:
            base = min(1.0, base + rng.uniform(0.1, 0.3))
        intensities.append(base)

    # Fill heightmap: each column's height profile is a ridge
    for x in range(min(time_periods, PX_W)):
        intensity = intensities[x]
        peak_y = PX_H // 2  # center ridge

        for y in range(PX_H):
            # Gaussian ridge centered at peak_y, width based on intensity
            dist = abs(y - peak_y)
            width = intensity * (PX_H * 0.4)
            if width > 0:
                h = intensity * math.exp(-0.5 * (dist / max(width, 1)) ** 2)
                # Add noise layers
                h += rng.uniform(-0.02, 0.02)
                # Secondary ridges from seed
                h += 0.1 * math.sin(y * 0.3 + seed * 0.1) * intensity
                h += 0.05 * math.sin(x * 0.2 + y * 0.15) * intensity
                heightmap[y][x] = max(0, h)

    return heightmap, intensities


def render_terrain(heightmap, time_periods, label):
    """Render heightmap as braille with elevation colors."""
    # Find max height for normalization
    max_h = 0
    for row in heightmap:
        for v in row:
            if v > max_h:
                max_h = v

    lines = []
    lines.append(f"\033[1;37m  {label}  ({time_periods} time slices)\033[0m")
    lines.append("")

    for row in range(ROWS):
        line = "  "
        for col in range(COLS):
            char_val = 0
            max_cell_h = 0
            has_pixel = False

            for dx in range(2):
                for dy in range(4):
                    px = col * 2 + dx
                    py = row * 4 + dy
                    if px < PX_W and py < PX_H:
                        h = heightmap[py][px]
                        # Threshold: show pixel if height > some minimum
                        if h > 0.05:
                            char_val |= DOT_MAP[(dx, dy)]
                            has_pixel = True
                            if h > max_cell_h:
                                max_cell_h = h

            if has_pixel:
                r, g, b = elevation_color(max_cell_h, max_h)
                line += f"\033[38;2;{r};{g};{b}m{chr(BRAILLE_BASE + char_val)}\033[0m"
            else:
                line += " "

        lines.append(line)

    # Time axis hint
    lines.append("")
    left = "  day 1"
    right = f"now (day {time_periods})"
    padding = COLS + 2 - len(left) - len(right)
    lines.append(f"\033[2m{left}{' ' * max(padding, 1)}{right}\033[0m")

    return "\n".join(lines)


def main():
    print("\033[2J\033[H")
    print("\033[1;36m" + "=" * 64 + "\033[0m")
    print("\033[1;36m  CANDIDATE C: Terrain / Topography\033[0m")
    print("\033[1;36m" + "=" * 64 + "\033[0m")
    print()
    print("  Time flows left→right. Height = session intensity.")
    print("  Deep blue = quiet. Green = active. White peaks = intense bursts.")
    print()

    stages = [
        (20, 77788, "Week 1"),
        (60, 77788, "Month 3"),
        (120, 77788, "Year 1"),
    ]

    for periods, seed, label in stages:
        heightmap, _ = generate_terrain(periods, seed)
        print(render_terrain(heightmap, periods, label))
        print()

    # Different user
    print("\033[1;33m" + "-" * 64 + "\033[0m")
    print("\033[1;33m  Different user, same time period (Year 1)\033[0m")
    print("\033[1;33m" + "-" * 64 + "\033[0m")
    print()
    heightmap2, _ = generate_terrain(120, 33344)
    print(render_terrain(heightmap2, 120, "Year 1 — different developer"))
    print()


if __name__ == "__main__":
    main()
