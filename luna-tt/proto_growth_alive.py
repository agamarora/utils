"""
Candidate A: Growth + Life Energy
The structure pulses with energy from center to edge.
New growth appears at the edges. Energy waves ripple when events arrive.
Ctrl+C to exit.
"""
import random
import math
import time
import sys
import os

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
CX, CY = PX_W // 2, PX_H // 2


def hsv_to_rgb(h, s, v):
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


class LivingGrowth:
    def __init__(self, seed=12345):
        self.rng = random.Random(seed)
        self.seed = seed
        self.grid = [[0] * PX_W for _ in range(PX_H)]
        self.dist = [[0.0] * PX_W for _ in range(PX_H)]  # distance from center
        self.grid[CY][CX] = 1
        self.dist[CY][CX] = 0.0
        self.deposited = 1
        self.max_radius = 3.0
        self.frame = 0
        self.pulse_waves = []  # (birth_time, speed)
        self.edge_pixels = set()  # pixels on the frontier

        # Pre-grow a base structure
        self._grow_batch(800)

    def _grow_batch(self, n):
        for _ in range(n):
            self._grow_one()

    def _grow_one(self):
        spawn_r = self.max_radius + 8
        if spawn_r > min(PX_W, PX_H) // 2 - 3:
            spawn_r = min(PX_W, PX_H) // 2 - 3

        angle = self.rng.uniform(0, 2 * math.pi)
        phase = (self.deposited / 3000) * 6.28
        bias = math.sin(phase * self.seed % 7 + self.seed) * 0.6
        angle += bias

        x = int(CX + spawn_r * math.cos(angle))
        y = int(CY + spawn_r * math.sin(angle))

        for _ in range(3000):
            dx = self.rng.choice([-1, 0, 1])
            dy = self.rng.choice([-1, 0, 1])
            nx, ny = x + dx, y + dy

            if nx < 1 or nx >= PX_W-1 or ny < 1 or ny >= PX_H-1:
                break

            stuck = False
            for ax in [-1, 0, 1]:
                for ay in [-1, 0, 1]:
                    if ax == 0 and ay == 0:
                        continue
                    if 0 <= nx+ax < PX_W and 0 <= ny+ay < PX_H:
                        if self.grid[ny+ay][nx+ax] > 0:
                            stuck = True
                            break
                if stuck:
                    break

            if stuck and self.grid[ny][nx] == 0:
                self.deposited += 1
                self.grid[ny][nx] = self.deposited
                d = math.sqrt((nx - CX)**2 + (ny - CY)**2)
                self.dist[ny][nx] = d
                if d > self.max_radius:
                    self.max_radius = d
                self.edge_pixels.add((nx, ny))
                # Remove from edge if now surrounded
                for ax in [-1, 0, 1]:
                    for ay in [-1, 0, 1]:
                        neighbor = (nx+ax, ny+ay)
                        # edges stay until they're no longer on the frontier
                break

            x, y = nx, ny

    def trigger_pulse(self):
        """Simulate an API event — sends energy wave from center."""
        self.pulse_waves.append((self.frame, 2.5 + self.rng.uniform(0, 1.5)))

    def get_energy(self, px, py, t):
        """Calculate energy level at a pixel for current frame."""
        if self.grid[py][px] == 0:
            return 0.0

        d = self.dist[py][px]
        energy = 0.0

        # Base breathing: slow sine wave, stronger at center
        center_factor = 1.0 - (d / max(self.max_radius, 1))
        energy += 0.15 * math.sin(t * 1.5 + d * 0.2) * center_factor

        # Pulse waves traveling outward
        for birth, speed in self.pulse_waves:
            age = (self.frame - birth) * 0.1
            wave_front = age * speed * 8
            wave_width = 6.0
            dist_to_wave = abs(d - wave_front)
            if dist_to_wave < wave_width:
                wave_strength = (1.0 - dist_to_wave / wave_width)
                # Waves fade as they travel
                fade = max(0, 1.0 - age * 0.15)
                energy += 0.6 * wave_strength * fade

        # Edge glow: pixels near the frontier shimmer
        if d > self.max_radius * 0.85:
            energy += 0.2 * (0.5 + 0.5 * math.sin(t * 3.0 + px * 0.5 + py * 0.7))

        return min(1.0, max(0.0, energy))

    def pixel_color(self, px, py, t):
        """Color a pixel based on its age, distance, and current energy."""
        if self.grid[py][px] == 0:
            return None

        d = self.dist[py][px]
        age_frac = self.grid[py][px] / max(self.deposited, 1)
        energy = self.get_energy(px, py, t)

        # Base color: deep teal center → warm amber edge
        t_dist = d / max(self.max_radius, 1)
        base_h = 190 - t_dist * 160  # teal → amber
        base_s = 0.6 + t_dist * 0.2
        base_v = 0.25 + t_dist * 0.25

        # Energy brightens and shifts hue toward white/cyan
        h = base_h + energy * 40
        s = max(0.1, base_s - energy * 0.4)
        v = min(1.0, base_v + energy * 0.55)

        return hsv_to_rgb(h % 360, s, v)

    def render_frame(self, t):
        """Render one frame as a string."""
        buf = []
        buf.append(f"\033[H")  # cursor home

        buf.append(f"\033[1;36m{'=' * 64}\033[0m\n")
        buf.append(f"\033[1;36m  GROWTH + LIFE ENERGY    "
                   f"\033[0;33mframe {self.frame}  "
                   f"particles: {self.deposited}  "
                   f"waves: {len(self.pulse_waves)}\033[0m\n")
        buf.append(f"\033[1;36m{'=' * 64}\033[0m\n\n")

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
                        if px < PX_W and py < PX_H:
                            c = self.pixel_color(px, py, t)
                            if c is not None:
                                char_val |= DOT_MAP[(dx, dy)]
                                r, g, b = c
                                v = r + g + b
                                if v > best_v:
                                    best_v = v
                                    best_color = c

                if char_val > 0 and best_color:
                    r, g, b = best_color
                    line += f"\033[38;2;{r};{g};{b}m{chr(BRAILLE_BASE + char_val)}\033[0m"
                else:
                    line += " "

            buf.append(line + "\n")

        buf.append(f"\n\033[2m  energy pulses from center → edge  |  "
                   f"Ctrl+C to exit\033[0m\n")

        return "".join(buf)

    def step(self):
        """Advance one frame."""
        self.frame += 1

        # Grow 2-5 particles per frame (simulates continuous accumulation)
        for _ in range(self.rng.randint(2, 5)):
            self._grow_one()

        # Random events (simulating API calls)
        if self.rng.random() < 0.06:
            self.trigger_pulse()

        # Clean old waves
        self.pulse_waves = [(b, s) for b, s in self.pulse_waves
                           if (self.frame - b) < 80]


def main():
    print("\033[2J\033[?25l")  # clear + hide cursor
    sys.stdout.flush()

    growth = LivingGrowth(seed=12345)

    try:
        while True:
            t = time.time()
            frame = growth.render_frame(t)
            sys.stdout.write(frame)
            sys.stdout.flush()
            growth.step()
            time.sleep(0.12)
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h")  # show cursor


if __name__ == "__main__":
    main()
