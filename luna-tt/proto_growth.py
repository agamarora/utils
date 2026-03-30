"""
Prototype: Organic Growth Structure (Candidate A)
Renders a DLA-like organic growth pattern using braille characters + true color.
Shows 3 stages to demonstrate time accumulation.
"""
import random
import math
import sys

# Braille character encoding: each cell is 2x4 dots
# Dot positions:  (0,0)=0x01 (0,1)=0x02 (0,2)=0x04 (1,0)=0x08
#                 (1,1)=0x10 (1,2)=0x20 (0,3)=0x40 (1,3)=0x80
BRAILLE_BASE = 0x2800
DOT_MAP = {
    (0, 0): 0x01, (1, 0): 0x08,
    (0, 1): 0x02, (1, 1): 0x10,
    (0, 2): 0x04, (1, 2): 0x20,
    (0, 3): 0x40, (1, 3): 0x80,
}

# Terminal grid size (characters)
COLS = 60
ROWS = 20

# Pixel grid size (braille sub-pixels)
PX_W = COLS * 2  # 120
PX_H = ROWS * 4  # 80

# Center of the growth
CX, CY = PX_W // 2, PX_H // 2


def hsv_to_rgb(h, s, v):
    """Convert HSV (0-360, 0-1, 0-1) to RGB (0-255)."""
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60:    r, g, b = c, x, 0
    elif h < 120: r, g, b = x, c, 0
    elif h < 180: r, g, b = 0, c, x
    elif h < 240: r, g, b = 0, x, c
    elif h < 300: r, g, b = x, 0, c
    else:         r, g, b = c, 0, x
    return int((r+m)*255), int((g+m)*255), int((b+m)*255)


def color_for_age(age, max_age):
    """Color based on when the pixel was deposited. Center=old=deep, edge=new=bright."""
    t = age / max(max_age, 1)
    # Deep teal core → warm amber edge
    h = 180 - t * 150  # 180 (teal) → 30 (amber)
    s = 0.7 + t * 0.2
    v = 0.3 + t * 0.5
    return hsv_to_rgb(h, s, v)


def generate_growth(num_particles, seed_data=None):
    """
    DLA-like growth. Particles random-walk from the edge and stick when they
    touch an existing particle. seed_data biases the walk direction to create
    asymmetric, unique shapes.
    """
    rng = random.Random(seed_data or 42)

    # Grid: 0 = empty, positive int = deposition order
    grid = [[0] * PX_W for _ in range(PX_H)]
    grid[CY][CX] = 1  # seed crystal

    deposited = 1
    max_radius = 3

    for i in range(num_particles):
        # Spawn on a circle just outside the current growth
        spawn_r = max_radius + 10
        if spawn_r > min(PX_W, PX_H) // 2 - 2:
            spawn_r = min(PX_W, PX_H) // 2 - 2

        angle = rng.uniform(0, 2 * math.pi)
        # Bias angle based on "usage data" — creates asymmetric bulges
        if seed_data:
            phase = (i / max(num_particles, 1)) * 6.28
            bias = math.sin(phase * seed_data % 7 + seed_data) * 0.8
            angle += bias

        x = int(CX + spawn_r * math.cos(angle))
        y = int(CY + spawn_r * math.sin(angle))

        # Random walk until we stick or go too far
        steps = 0
        while steps < 5000:
            dx = rng.choice([-1, 0, 1])
            dy = rng.choice([-1, 0, 1])
            nx, ny = x + dx, y + dy

            if nx < 1 or nx >= PX_W-1 or ny < 1 or ny >= PX_H-1:
                break  # out of bounds, discard

            # Check if any neighbor is occupied
            stuck = False
            for ax in [-1, 0, 1]:
                for ay in [-1, 0, 1]:
                    if ax == 0 and ay == 0:
                        continue
                    if 0 <= nx+ax < PX_W and 0 <= ny+ay < PX_H:
                        if grid[ny+ay][nx+ax] > 0:
                            stuck = True
                            break
                if stuck:
                    break

            if stuck and grid[ny][nx] == 0:
                deposited += 1
                grid[ny][nx] = deposited
                dist = math.sqrt((nx - CX)**2 + (ny - CY)**2)
                if dist > max_radius:
                    max_radius = dist
                break

            x, y = nx, ny
            steps += 1

    return grid, deposited


def render_braille(grid, total_deposited, label):
    """Convert pixel grid to braille characters with true color."""
    lines = []
    lines.append(f"\033[1;37m  {label}\033[0m")
    lines.append("")

    for row in range(ROWS):
        line = "  "
        for col in range(COLS):
            # Collect the 2x4 sub-pixel block
            char_val = 0
            max_age = 0
            has_pixel = False

            for dx in range(2):
                for dy in range(4):
                    px = col * 2 + dx
                    py = row * 4 + dy
                    if px < PX_W and py < PX_H and grid[py][px] > 0:
                        char_val |= DOT_MAP[(dx, dy)]
                        has_pixel = True
                        if grid[py][px] > max_age:
                            max_age = grid[py][px]

            if has_pixel:
                r, g, b = color_for_age(max_age, total_deposited)
                line += f"\033[38;2;{r};{g};{b}m{chr(BRAILLE_BASE + char_val)}\033[0m"
            else:
                line += " "

        lines.append(line)

    return "\n".join(lines)


def main():
    stages = [
        (150, 12345, "Day 7 — first week"),
        (1200, 12345, "Day 90 — three months"),
        (4000, 12345, "Day 365 — one year"),
    ]

    print("\033[2J\033[H")  # clear screen
    print("\033[1;36m" + "=" * 64 + "\033[0m")
    print("\033[1;36m  CANDIDATE A: Organic Growth Structure (DLA)\033[0m")
    print("\033[1;36m" + "=" * 64 + "\033[0m")
    print()
    print("  Same seed (same user), different amounts of accumulated data.")
    print("  Center = day 1. Edge = now. Color shifts from deep teal to warm amber.")
    print()

    for particles, seed, label in stages:
        sys.stderr.write(f"\r  Generating {label}...   ")
        grid, total = generate_growth(particles, seed)
        sys.stderr.write("\r" + " " * 40 + "\r")
        print(render_braille(grid, total, label))
        print()

    # Show a DIFFERENT seed to demonstrate uniqueness
    print("\033[1;33m" + "-" * 64 + "\033[0m")
    print("\033[1;33m  Different user (different seed), same time period (Day 365)\033[0m")
    print("\033[1;33m" + "-" * 64 + "\033[0m")
    print()
    sys.stderr.write(f"\r  Generating alternate user...   ")
    grid2, total2 = generate_growth(4000, 99887)
    sys.stderr.write("\r" + " " * 40 + "\r")
    print(render_braille(grid2, total2, "Day 365 — different developer"))
    print()


if __name__ == "__main__":
    main()
