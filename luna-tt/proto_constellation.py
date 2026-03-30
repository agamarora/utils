"""
Prototype: Constellation / Star Field (Candidate B)
Each session = a star. Brightness = tokens. Color = model.
Shows 3 stages: week 1, month 3, year 1.
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

# Model colors (warm palette)
MODEL_COLORS = {
    "opus":   (255, 140, 50),   # warm orange
    "sonnet": (100, 180, 255),  # cool blue
    "haiku":  (160, 230, 130),  # soft green
}


def generate_sessions(count, seed):
    """Generate fake session data: (x, y, brightness, model, tokens)."""
    rng = random.Random(seed)
    sessions = []
    models = ["opus", "sonnet", "haiku"]

    # Cluster centers emerge from the seed — like areas of focus
    n_clusters = 3 + (seed % 5)
    clusters = [(rng.uniform(15, PX_W-15), rng.uniform(10, PX_H-10)) for _ in range(n_clusters)]

    for i in range(count):
        # Pick a cluster with some probability, or go random
        if rng.random() < 0.7:
            cx, cy = rng.choice(clusters)
            x = cx + rng.gauss(0, 8 + i * 0.01)
            y = cy + rng.gauss(0, 5 + i * 0.01)
        else:
            x = rng.uniform(5, PX_W - 5)
            y = rng.uniform(5, PX_H - 5)

        x = max(0, min(PX_W - 1, int(x)))
        y = max(0, min(PX_H - 1, int(y)))

        model = rng.choice(models)
        tokens = rng.randint(500, 50000)
        brightness = min(1.0, tokens / 30000)

        sessions.append((x, y, brightness, model, tokens))

    return sessions


def render_constellation(sessions, label):
    """Render sessions as braille stars with true color."""
    # Build pixel grid: store (brightness, model) per pixel
    pixels = {}
    for x, y, br, model, _ in sessions:
        key = (x, y)
        if key not in pixels or br > pixels[key][0]:
            pixels[key] = (br, model)

    lines = []
    lines.append(f"\033[1;37m  {label}  ({len(sessions)} sessions)\033[0m")
    lines.append("")

    for row in range(ROWS):
        line = "  "
        for col in range(COLS):
            char_val = 0
            best_br = 0
            best_model = None

            for dx in range(2):
                for dy in range(4):
                    px = col * 2 + dx
                    py = row * 4 + dy
                    if (px, py) in pixels:
                        char_val |= DOT_MAP[(dx, dy)]
                        br, model = pixels[(px, py)]
                        if br > best_br:
                            best_br = br
                            best_model = model

            if char_val > 0 and best_model:
                r, g, b = MODEL_COLORS[best_model]
                # Dim by brightness
                r = int(r * (0.3 + 0.7 * best_br))
                g = int(g * (0.3 + 0.7 * best_br))
                b = int(b * (0.3 + 0.7 * best_br))
                line += f"\033[38;2;{r};{g};{b}m{chr(BRAILLE_BASE + char_val)}\033[0m"
            else:
                # Dim background stars (ambiance)
                if random.random() < 0.008:
                    v = random.randint(30, 60)
                    dot = random.choice(list(DOT_MAP.values()))
                    line += f"\033[38;2;{v};{v};{v+10}m{chr(BRAILLE_BASE + dot)}\033[0m"
                else:
                    line += " "

        lines.append(line)

    # Legend
    lines.append("")
    lines.append("  \033[38;2;255;140;50m●\033[0m opus  "
                 "\033[38;2;100;180;255m●\033[0m sonnet  "
                 "\033[38;2;160;230;130m●\033[0m haiku  "
                 "(brighter = more tokens)")

    return "\n".join(lines)


def main():
    print("\033[2J\033[H")
    print("\033[1;36m" + "=" * 64 + "\033[0m")
    print("\033[1;36m  CANDIDATE B: Constellation / Star Field\033[0m")
    print("\033[1;36m" + "=" * 64 + "\033[0m")
    print()
    print("  Each dot = a session. Color = model. Brightness = token count.")
    print("  Clusters emerge from your usage patterns.")
    print()

    stages = [
        (20, 54321, "Week 1"),
        (180, 54321, "Month 3"),
        (700, 54321, "Year 1"),
    ]

    for count, seed, label in stages:
        sessions = generate_sessions(count, seed)
        print(render_constellation(sessions, label))
        print()

    # Different user
    print("\033[1;33m" + "-" * 64 + "\033[0m")
    print("\033[1;33m  Different user, same time period (Year 1)\033[0m")
    print("\033[1;33m" + "-" * 64 + "\033[0m")
    print()
    sessions2 = generate_sessions(700, 11223)
    print(render_constellation(sessions2, "Year 1 — different developer"))
    print()


if __name__ == "__main__":
    main()
