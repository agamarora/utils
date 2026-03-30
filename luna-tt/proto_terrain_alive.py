"""
Candidate C: Terrain + Civilization Building
A landscape grows left to right. Settlements appear. Roads connect them.
Smoke rises from active villages. New territory unlocked as you work.
Ctrl+C to exit.
"""
import random
import math
import time
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
PX_W = COLS * 2
PX_H = ROWS * 4


def elevation_color(h, max_h, t, px, py):
    """Color with animated water and weather."""
    frac = h / max(max_h, 0.01)

    if frac < 0.12:
        # Deep water — shimmers
        wave = 0.8 + 0.2 * math.sin(t * 1.5 + px * 0.3 + py * 0.2)
        return (int(15 * wave), int(25 * wave), int(55 * wave))
    elif frac < 0.25:
        # Shallow water — gentle movement
        wave = 0.85 + 0.15 * math.sin(t * 2.0 + px * 0.5)
        return (int(30 * wave), int(55 * wave), int(85 * wave))
    elif frac < 0.40:
        # Beach/lowlands
        return (60, 110, 55)
    elif frac < 0.55:
        # Grasslands — sway
        sway = 0.9 + 0.1 * math.sin(t * 0.7 + px * 0.15)
        return (int(70 * sway), int(145 * sway), int(50 * sway))
    elif frac < 0.70:
        # Hills
        return (120, 120, 50)
    elif frac < 0.85:
        # Mountains
        return (140, 95, 50)
    else:
        # Snow — sparkle
        sparkle = 0.85 + 0.15 * math.sin(t * 3.0 + px * py * 0.01)
        v = int(215 * sparkle)
        return (v, v, min(255, v + 15))


class Settlement:
    def __init__(self, x, y, size, name_seed, rng):
        self.x = x
        self.y = y
        self.size = size  # 1=village, 2=town, 3=city
        self.birth_time = time.time()
        # Settlement color — warm tones
        self.color = (
            180 + rng.randint(0, 60),
            120 + rng.randint(0, 80),
            40 + rng.randint(0, 40),
        )
        self.smoke_phase = rng.uniform(0, 6.28)

    def smoke_particles(self, t):
        """Return smoke pixel positions above the settlement."""
        particles = []
        for i in range(self.size + 1):
            sx = self.x + math.sin(t * 1.5 + i + self.smoke_phase) * 1.5
            sy = self.y - 3 - i * 2 - math.sin(t * 0.8 + i * 0.5) * 1.0
            # Smoke fades as it rises
            alpha = max(0.1, 1.0 - i * 0.25)
            v = int(60 * alpha)
            particles.append((int(sx), int(sy), (v, v, v + 10)))
        return particles


class LivingTerrain:
    def __init__(self, seed=77788):
        self.rng = random.Random(seed)
        self.seed = seed
        self.heightmap = [[0.0] * PX_W for _ in range(PX_H)]
        self.frame = 0
        self.frontier = 0  # how far right the terrain has been revealed
        self.settlements = []
        self.roads = []  # (settlement_i, settlement_j)
        self.max_h = 0.5

        # Generate base terrain for the full width
        self._generate_full_terrain()
        # Start with some revealed
        self.frontier = 30

        # Place initial settlements
        for _ in range(3):
            self._place_settlement()

    def _generate_full_terrain(self):
        """Pre-generate the heightmap. Each column = a time period."""
        base = 0.4
        for x in range(PX_W):
            # Random walk intensity
            base += self.rng.gauss(0, 0.03)
            base = max(0.15, min(0.95, base))
            if self.rng.random() < 0.08:
                base = min(1.0, base + self.rng.uniform(0.1, 0.25))

            peak_y = PX_H // 2
            for y in range(PX_H):
                dist = abs(y - peak_y)
                width = base * (PX_H * 0.4)
                if width > 0:
                    h = base * math.exp(-0.5 * (dist / max(width, 1)) ** 2)
                    h += self.rng.uniform(-0.015, 0.015)
                    h += 0.08 * math.sin(y * 0.25 + self.seed * 0.1) * base
                    h += 0.04 * math.sin(x * 0.15 + y * 0.1) * base
                    # Mountain ridges
                    h += 0.1 * max(0, math.sin(x * 0.08 + self.seed)) * base
                    self.heightmap[y][x] = max(0, h)
                    if h > self.max_h:
                        self.max_h = h

    def _place_settlement(self):
        """Place a settlement on suitable terrain."""
        for _ in range(50):  # tries
            x = self.rng.randint(5, min(self.frontier * 2, PX_W - 5))
            y = self.rng.randint(PX_H // 4, 3 * PX_H // 4)
            h = self.heightmap[y][x]
            frac = h / max(self.max_h, 0.01)
            # Settle on grasslands/hills, not water or mountains
            if 0.35 < frac < 0.75:
                # Not too close to existing settlements
                too_close = False
                for s in self.settlements:
                    if abs(s.x - x) < 15 and abs(s.y - y) < 10:
                        too_close = True
                        break
                if not too_close:
                    size = self.rng.choice([1, 1, 1, 2, 2, 3])
                    self.settlements.append(
                        Settlement(x, y, size, self.rng.randint(0, 999), self.rng))
                    # Connect to nearest settlement
                    if len(self.settlements) > 1:
                        nearest = min(range(len(self.settlements) - 1),
                                     key=lambda i: abs(self.settlements[i].x - x)
                                     + abs(self.settlements[i].y - y))
                        self.roads.append((len(self.settlements) - 1, nearest))
                    return

    def render_frame(self, t):
        buf = []
        buf.append("\033[H")

        buf.append(f"\033[1;36m{'=' * 64}\033[0m\n")
        buf.append(f"\033[1;36m  TERRAIN + CIVILIZATION    "
                   f"\033[0;33msettlements: {len(self.settlements)}  "
                   f"frontier: {self.frontier}/{PX_W//2}\033[0m\n")
        buf.append(f"\033[1;36m{'=' * 64}\033[0m\n\n")

        # Collect extra pixels: settlements, roads, smoke
        extras = {}

        # Roads
        for si, sj in self.roads:
            s1, s2 = self.settlements[si], self.settlements[sj]
            steps = int(math.sqrt((s1.x-s2.x)**2 + (s1.y-s2.y)**2))
            for k in range(steps + 1):
                frac = k / max(steps, 1)
                lx = int(s1.x + (s2.x - s1.x) * frac)
                ly = int(s1.y + (s2.y - s1.y) * frac)
                if 0 <= lx < PX_W and 0 <= ly < PX_H:
                    extras[(lx, ly)] = (100, 85, 50)

        # Settlements
        for s in self.settlements:
            # Settlement footprint
            r = s.size + 1
            for dx in range(-r, r+1):
                for dy in range(-r, r+1):
                    px, py = s.x + dx, s.y + dy
                    if 0 <= px < PX_W and 0 <= py < PX_H:
                        dist = math.sqrt(dx*dx + dy*dy)
                        if dist <= r:
                            # Pulsing glow
                            pulse = 0.8 + 0.2 * math.sin(t * 1.2 + s.smoke_phase)
                            cr, cg, cb = s.color
                            extras[(px, py)] = (int(cr * pulse), int(cg * pulse), int(cb * pulse))

            # Smoke
            for sx, sy, sc in s.smoke_particles(t):
                if 0 <= sx < PX_W and 0 <= sy < PX_H:
                    extras[(sx, sy)] = sc

        # Frontier fog: pixels beyond frontier are dimmed
        frontier_px = self.frontier * 2

        for row in range(ROWS):
            line = "  "
            for col in range(COLS):
                char_val = 0
                best_color = None
                best_v = -1

                for dx in range(2):
                    for dy in range(4):
                        px = col * 2 + dx
                        py = row * 4 + dy

                        # Check extras first (settlements, roads, smoke)
                        if (px, py) in extras:
                            char_val |= DOT_MAP[(dx, dy)]
                            r, g, b = extras[(px, py)]
                            v = r + g + b
                            if v > best_v:
                                best_v = v
                                best_color = (r, g, b)
                        elif px < PX_W and py < PX_H:
                            h = self.heightmap[py][px]
                            if h > 0.04:
                                char_val |= DOT_MAP[(dx, dy)]
                                r, g, b = elevation_color(h, self.max_h, t, px, py)

                                # Fog of war: dim beyond frontier
                                if px > frontier_px:
                                    fog = max(0.1, 1.0 - (px - frontier_px) / 30)
                                    r = int(r * fog)
                                    g = int(g * fog)
                                    b = int(b * fog)

                                v = r + g + b
                                if v > best_v:
                                    best_v = v
                                    best_color = (r, g, b)

                if char_val > 0 and best_color:
                    r, g, b = best_color
                    line += f"\033[38;2;{r};{g};{b}m{chr(BRAILLE_BASE + char_val)}\033[0m"
                else:
                    line += " "

            buf.append(line + "\n")

        buf.append(f"\n\033[2m  ← day 1{'.' * 36}now →  |  "
                   f"Ctrl+C to exit\033[0m\n")

        return "".join(buf)

    def step(self):
        self.frame += 1

        # Slowly reveal more terrain (frontier advances)
        if self.frontier < PX_W // 2 - 1:
            if self.frame % 8 == 0:
                self.frontier += 1

        # Occasionally place new settlements
        if self.rng.random() < 0.02 and len(self.settlements) < 15:
            self._place_settlement()

        # Grow existing settlements
        if self.rng.random() < 0.01:
            if self.settlements:
                s = self.rng.choice(self.settlements)
                if s.size < 3:
                    s.size += 1


def main():
    print("\033[2J\033[?25l")
    sys.stdout.flush()

    world = LivingTerrain(seed=77788)

    try:
        while True:
            t = time.time()
            frame = world.render_frame(t)
            sys.stdout.write(frame)
            sys.stdout.flush()
            world.step()
            time.sleep(0.12)
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h")


if __name__ == "__main__":
    main()
