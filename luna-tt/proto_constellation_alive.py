"""
Candidate B: Constellation + Universe Doing Universe Things
Stars twinkle. New stars are born with a flash. Nebulae drift.
Connections form between nearby stars. Occasional supernovae.
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

MODEL_COLORS = {
    "opus":   (255, 140, 50),
    "sonnet": (100, 180, 255),
    "haiku":  (160, 230, 130),
}


class Star:
    def __init__(self, x, y, model, tokens, birth_frame, rng):
        self.x = x
        self.y = y
        self.model = model
        self.tokens = tokens
        self.base_brightness = min(1.0, tokens / 25000)
        self.birth_frame = birth_frame
        # Each star has its own twinkle rhythm
        self.twinkle_speed = rng.uniform(1.5, 4.0)
        self.twinkle_phase = rng.uniform(0, 6.28)
        self.supernova = False
        self.supernova_frame = 0

    def brightness(self, frame, t):
        # Birth flash: bright then settle
        age = frame - self.birth_frame
        if age < 15:
            flash = 1.0 - (age / 15) * 0.6
        else:
            flash = 0.4

        # Twinkle
        twinkle = 0.5 + 0.5 * math.sin(t * self.twinkle_speed + self.twinkle_phase)

        # Supernova
        if self.supernova:
            sn_age = frame - self.supernova_frame
            if sn_age < 30:
                return min(1.0, 0.8 + 0.2 * math.sin(sn_age * 0.5))
            elif sn_age < 60:
                return max(0.1, 0.8 - (sn_age - 30) / 40)

        return self.base_brightness * (0.3 + 0.7 * twinkle * flash)

    def color(self, frame, t):
        br = self.brightness(frame, t)
        base_r, base_g, base_b = MODEL_COLORS[self.model]

        if self.supernova:
            sn_age = frame - self.supernova_frame
            if sn_age < 30:
                # White-hot
                return (
                    min(255, int(220 + 35 * math.sin(sn_age * 0.3))),
                    min(255, int(200 + 55 * math.sin(sn_age * 0.4))),
                    min(255, int(180 + 75 * math.sin(sn_age * 0.5)))
                )
            else:
                # Fade to dim remnant
                fade = max(0.1, 1.0 - (sn_age - 30) / 60)
                return (int(base_r * fade), int(base_g * fade), int(base_b * fade))

        return (
            int(base_r * br),
            int(base_g * br),
            int(base_b * br),
        )


class Nebula:
    """A drifting cloud of color."""
    def __init__(self, x, y, radius, color, rng):
        self.x = x
        self.y = y
        self.radius = radius
        self.color = color
        self.dx = rng.uniform(-0.05, 0.05)
        self.dy = rng.uniform(-0.02, 0.02)
        self.phase = rng.uniform(0, 6.28)

    def move(self):
        self.x += self.dx
        self.y += self.dy
        # Wrap
        if self.x < -10: self.x = PX_W + 10
        if self.x > PX_W + 10: self.x = -10
        if self.y < -10: self.y = PX_H + 10
        if self.y > PX_H + 10: self.y = -10

    def influence(self, px, py, t):
        dist = math.sqrt((px - self.x)**2 + (py - self.y)**2)
        if dist > self.radius:
            return None
        # Soft falloff with breathing
        strength = (1.0 - dist / self.radius) ** 2
        strength *= 0.3 + 0.15 * math.sin(t * 0.8 + self.phase + dist * 0.1)
        r, g, b = self.color
        return (int(r * strength * 0.3), int(g * strength * 0.3), int(b * strength * 0.3))


class LivingConstellation:
    def __init__(self, seed=54321):
        self.rng = random.Random(seed)
        self.seed = seed
        self.stars = []
        self.nebulae = []
        self.frame = 0
        self.connections = []  # (star_i, star_j, strength)

        # Cluster centers
        n_clusters = 3 + (seed % 4)
        self.clusters = [(self.rng.uniform(15, PX_W-15),
                         self.rng.uniform(10, PX_H-10)) for _ in range(n_clusters)]

        # Initial nebulae
        nebula_colors = [(60, 30, 80), (30, 50, 80), (80, 40, 30), (30, 70, 50)]
        for _ in range(3):
            self.nebulae.append(Nebula(
                self.rng.uniform(10, PX_W-10),
                self.rng.uniform(10, PX_H-10),
                self.rng.uniform(15, 30),
                self.rng.choice(nebula_colors),
                self.rng
            ))

        # Seed with some initial stars
        for _ in range(80):
            self._birth_star()

    def _birth_star(self):
        models = ["opus", "sonnet", "haiku"]
        if self.rng.random() < 0.7:
            cx, cy = self.rng.choice(self.clusters)
            x = cx + self.rng.gauss(0, 10)
            y = cy + self.rng.gauss(0, 6)
        else:
            x = self.rng.uniform(3, PX_W - 3)
            y = self.rng.uniform(3, PX_H - 3)

        x = max(0, min(PX_W - 1, int(x)))
        y = max(0, min(PX_H - 1, int(y)))
        model = self.rng.choice(models)
        tokens = self.rng.randint(500, 50000)
        self.stars.append(Star(x, y, model, tokens, self.frame, self.rng))

    def _update_connections(self):
        """Find nearby star pairs to draw faint lines between."""
        self.connections = []
        if len(self.stars) < 2:
            return
        # Only check recent stars for performance
        recent = self.stars[-200:]
        for i in range(len(recent)):
            for j in range(i+1, min(i+20, len(recent))):
                dx = recent[i].x - recent[j].x
                dy = recent[i].y - recent[j].y
                dist = math.sqrt(dx*dx + dy*dy)
                if dist < 12:
                    strength = 1.0 - dist / 12
                    self.connections.append((recent[i], recent[j], strength))

    def render_frame(self, t):
        buf = []
        buf.append("\033[H")

        buf.append(f"\033[1;36m{'=' * 64}\033[0m\n")
        buf.append(f"\033[1;36m  CONSTELLATION + UNIVERSE    "
                   f"\033[0;33mstars: {len(self.stars)}  "
                   f"nebulae: {len(self.nebulae)}\033[0m\n")
        buf.append(f"\033[1;36m{'=' * 64}\033[0m\n\n")

        # Build pixel buffer: (r, g, b) per pixel
        pixels = {}

        # Nebula background
        for row in range(ROWS):
            for col in range(COLS):
                px, py = col * 2, row * 4
                for neb in self.nebulae:
                    inf = neb.influence(px, py, t)
                    if inf:
                        r, g, b = inf
                        if (px, py) in pixels:
                            pr, pg, pb = pixels[(px, py)]
                            pixels[(px, py)] = (min(255, pr+r), min(255, pg+g), min(255, pb+b))
                        else:
                            pixels[(px, py)] = (r, g, b)

        # Connection lines (faint)
        for s1, s2, strength in self.connections:
            steps = int(math.sqrt((s1.x-s2.x)**2 + (s1.y-s2.y)**2))
            for k in range(steps + 1):
                frac = k / max(steps, 1)
                lx = int(s1.x + (s2.x - s1.x) * frac)
                ly = int(s1.y + (s2.y - s1.y) * frac)
                if 0 <= lx < PX_W and 0 <= ly < PX_H:
                    v = int(40 * strength * (0.5 + 0.5 * math.sin(t * 2 + k * 0.3)))
                    pixels[(lx, ly)] = (v + 20, v + 25, v + 40)

        # Stars
        for star in self.stars:
            c = star.color(self.frame, t)
            pixels[(star.x, star.y)] = c
            # Bright stars get a small glow
            br = star.brightness(self.frame, t)
            if br > 0.6 or star.supernova:
                for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                    gx, gy = star.x+dx, star.y+dy
                    if 0 <= gx < PX_W and 0 <= gy < PX_H:
                        gr, gg, gb = c
                        glow_f = 0.3 if not star.supernova else 0.6
                        pixels[(gx, gy)] = (int(gr*glow_f), int(gg*glow_f), int(gb*glow_f))

        # Render to braille
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
                        if (px, py) in pixels:
                            r, g, b = pixels[(px, py)]
                            if r + g + b > 10:
                                char_val |= DOT_MAP[(dx, dy)]
                                v = r + g + b
                                if v > best_v:
                                    best_v = v
                                    best_color = (r, g, b)

                if char_val > 0 and best_color:
                    r, g, b = best_color
                    line += f"\033[38;2;{r};{g};{b}m{chr(BRAILLE_BASE + char_val)}\033[0m"
                else:
                    # Very faint background dust
                    if self.rng.random() < 0.004:
                        v = self.rng.randint(15, 30)
                        dot = self.rng.choice(list(DOT_MAP.values()))
                        line += f"\033[38;2;{v};{v};{v+5}m{chr(BRAILLE_BASE + dot)}\033[0m"
                    else:
                        line += " "

            buf.append(line + "\n")

        buf.append(f"\n  \033[38;2;255;140;50m●\033[0m opus  "
                   f"\033[38;2;100;180;255m●\033[0m sonnet  "
                   f"\033[38;2;160;230;130m●\033[0m haiku"
                   f"\033[2m  |  Ctrl+C to exit\033[0m\n")

        return "".join(buf)

    def step(self):
        self.frame += 1

        # New star every few frames
        if self.rng.random() < 0.15:
            self._birth_star()

        # Rare supernova
        if self.rng.random() < 0.008 and len(self.stars) > 20:
            star = self.rng.choice(self.stars[-50:])
            if not star.supernova:
                star.supernova = True
                star.supernova_frame = self.frame

        # Move nebulae
        for neb in self.nebulae:
            neb.move()

        # Update connections periodically
        if self.frame % 10 == 0:
            self._update_connections()


def main():
    print("\033[2J\033[?25l")
    sys.stdout.flush()

    universe = LivingConstellation(seed=54321)

    try:
        while True:
            t = time.time()
            frame = universe.render_frame(t)
            sys.stdout.write(frame)
            sys.stdout.flush()
            universe.step()
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h")


if __name__ == "__main__":
    main()
