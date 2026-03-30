use crate::types::{GrowthInfo, ProxyEvent, SystemMorphs};
use crate::ui::colors::hsv_to_rgb;
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use ratatui::style::{Color, Style};
use ratatui::widgets::canvas::{Canvas, Context, Painter, Shape};
use ratatui::Frame;
use ratatui::layout::Rect;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::f64::consts::{E, PI};
use std::path::Path;

/// Golden ratio
const PHI: f64 = 1.618033988749895;

/// Internal grid size (fixed, terminal-independent)
const GRID_SIZE: usize = 256;

/// Max random walk steps before discarding a particle
const MAX_WALK_STEPS: u32 = 3000;

/// Max age for a pulse wave in ticks
const MAX_PULSE_AGE: u32 = 60;

/// Initial burst of particles on fresh install
const BIRTH_BURST: u32 = 50;

// --- Serializable pixel ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Pixel {
    pub x: u16,
    pub y: u16,
    pub order: u32,
    pub parent: Option<u32>,
    pub depth: u16,
    pub model_hash: f64,
    pub cache_ratio: f64,
}

// --- Pulse wave for BFS energy ---

struct PulseWave {
    frontier: Vec<u32>,       // current wave front (pixel orders)
    visited: HashSet<u32>,    // already illuminated pixels
    birth_tick: u32,
    intensity: f64,
}

// --- Growth state ---

pub struct GrowthState {
    grid: Vec<bool>,                        // GRID_SIZE x GRID_SIZE occupancy
    pixels: Vec<Pixel>,
    order_to_index: HashMap<u32, usize>,    // order -> index in pixels vec
    children_map: HashMap<u32, Vec<u32>>,   // parent_order -> children orders
    max_radius: f64,
    max_depth: u16,
    seed: u64,
    rng: StdRng,
    pulse_waves: Vec<PulseWave>,
    pulse_energy: HashMap<u32, f64>,        // pixel order -> current pulse brightness
    current_tick: u32,
    current_morphs: SystemMorphs,
    last_event: Option<ProxyEvent>,
    created_at: String,
    is_fresh: bool,                         // true on first ever creation
}

impl GrowthState {
    pub fn new(seed: u64) -> Self {
        let mut state = Self {
            grid: vec![false; GRID_SIZE * GRID_SIZE],
            pixels: Vec::new(),
            order_to_index: HashMap::new(),
            children_map: HashMap::new(),
            max_radius: 0.0,
            max_depth: 0,
            seed,
            rng: StdRng::seed_from_u64(seed),
            pulse_waves: Vec::new(),
            pulse_energy: HashMap::new(),
            current_tick: 0,
            current_morphs: SystemMorphs::default(),
            last_event: None,
            created_at: chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string(),
            is_fresh: true,
        };

        // Seed crystal at center
        let cx = (GRID_SIZE / 2) as u16;
        let cy = (GRID_SIZE / 2) as u16;
        let pixel = Pixel {
            x: cx,
            y: cy,
            order: 0,
            parent: None,
            depth: 0,
            model_hash: 0.0,
            cache_ratio: 0.0,
        };
        state.grid[cy as usize * GRID_SIZE + cx as usize] = true;
        state.order_to_index.insert(0, 0);
        state.pixels.push(pixel);

        state
    }

    /// Grow a batch of particles (used for birth burst).
    pub fn grow_batch(&mut self, n: u32) {
        let morphs = self.current_morphs.clone();
        let event = self.last_event.clone();
        for _ in 0..n {
            self.grow_one(&morphs, &event);
        }
    }

    /// Grow a single particle using DLA with golden-angle + pi + e based angles.
    fn grow_one(&mut self, morphs: &SystemMorphs, event: &Option<ProxyEvent>) {
        let deposited = self.pixels.len() as f64;
        let seed_fract = (self.seed as f64 / u64::MAX as f64).fract().abs();

        // Compute launch angle using golden angle + pi + e
        let phase = deposited * PI * seed_fract;
        let mut angle = 2.0 * PI * (phase * PHI).fract();
        angle += (phase * PI * seed_fract).sin() * 0.6;

        // Input tokens widen spread
        if let Some(ref ev) = event {
            angle += ev.input_tokens * PI * 0.3;
        }

        // Rate limit: sharp bend using Euler's number
        let is_rate_limited = event.as_ref().map(|e| e.is_rate_limited).unwrap_or(false);
        if is_rate_limited {
            angle += PI * (seed_fract * E).fract();
        }

        // Spawn walker at edge (max_radius + margin)
        let spawn_r = self.max_radius + (GRID_SIZE as f64 * 0.06);
        let spawn_r = spawn_r.max(GRID_SIZE as f64 * 0.05);
        let cx = (GRID_SIZE / 2) as f64;
        let cy = (GRID_SIZE / 2) as f64;
        let mut wx = cx + spawn_r * angle.cos();
        let mut wy = cy + spawn_r * angle.sin();

        // Step jitter: disk activity = more chaotic
        let step_jitter = 0.8 * (1.0 + morphs.disk_active * 2.0);

        for _ in 0..MAX_WALK_STEPS {
            // Random walk step
            wx += self.rng.gen_range(-step_jitter..step_jitter);
            wy += self.rng.gen_range(-step_jitter..step_jitter);

            let gx = wx.round() as i32;
            let gy = wy.round() as i32;

            // Out of bounds check
            if gx < 0 || gy < 0 || gx >= GRID_SIZE as i32 || gy >= GRID_SIZE as i32 {
                return; // Discard
            }

            let gx = gx as usize;
            let gy = gy as usize;

            // Already occupied? Skip (we can't deposit here)
            if self.grid[gy * GRID_SIZE + gx] {
                continue;
            }

            // Check 8-connected neighbors for occupied cell
            if let Some(neighbor_order) = self.find_occupied_neighbor(gx, gy) {
                // STICK: first contact
                let new_order = self.pixels.len() as u32;
                let parent_depth = self.pixels[self.order_to_index[&neighbor_order]].depth;
                let depth = parent_depth + 1;

                let model_hash = event.as_ref().map(|e| e.model_hash).unwrap_or(0.5);
                let cache_ratio = event.as_ref().map(|e| e.cache_ratio).unwrap_or(0.0);

                let pixel = Pixel {
                    x: gx as u16,
                    y: gy as u16,
                    order: new_order,
                    parent: Some(neighbor_order),
                    depth,
                    model_hash,
                    cache_ratio,
                };

                self.grid[gy * GRID_SIZE + gx] = true;
                self.order_to_index.insert(new_order, self.pixels.len());
                self.children_map.entry(neighbor_order).or_default().push(new_order);
                self.pixels.push(pixel);

                // Update max depth and radius
                if depth > self.max_depth {
                    self.max_depth = depth;
                }
                let dx = gx as f64 - cx;
                let dy = gy as f64 - cy;
                let r = (dx * dx + dy * dy).sqrt();
                if r > self.max_radius {
                    self.max_radius = r;
                }

                return;
            }
        }
        // Discarded after max steps
    }

    /// Find an occupied 8-connected neighbor and return its order.
    fn find_occupied_neighbor(&self, gx: usize, gy: usize) -> Option<u32> {
        for dy in [-1i32, 0, 1] {
            for dx in [-1i32, 0, 1] {
                if dx == 0 && dy == 0 {
                    continue;
                }
                let nx = gx as i32 + dx;
                let ny = gy as i32 + dy;
                if nx >= 0 && ny >= 0 && nx < GRID_SIZE as i32 && ny < GRID_SIZE as i32 {
                    let nx = nx as usize;
                    let ny = ny as usize;
                    if self.grid[ny * GRID_SIZE + nx] {
                        // Find the pixel at this location
                        // Linear scan of recent pixels (growth tends to happen at tips)
                        for pixel in self.pixels.iter().rev() {
                            if pixel.x as usize == nx && pixel.y as usize == ny {
                                return Some(pixel.order);
                            }
                        }
                    }
                }
            }
        }
        None
    }

    /// Tick: grow particles based on utilization, advance pulse BFS.
    pub fn tick(&mut self, morphs: &SystemMorphs) {
        self.current_morphs = morphs.clone();
        self.current_tick += 1;

        // Growth rate: base + utilization + tokens
        let util_5h = self.last_event.as_ref().map(|e| e.five_h_utilization).unwrap_or(0.0);
        let tokens_out = self.last_event.as_ref().map(|e| e.output_tokens).unwrap_or(0.0);
        let particles_this_frame = 2 + (util_5h * 5.0 + tokens_out * 3.0) as u32;

        let morphs_clone = morphs.clone();
        let event_clone = self.last_event.clone();
        for _ in 0..particles_this_frame {
            self.grow_one(&morphs_clone, &event_clone);
        }

        // Advance pulse waves
        self.advance_pulses();
    }

    /// Ingest a proxy event to feed growth parameters.
    pub fn ingest(&mut self, event: ProxyEvent) {
        self.last_event = Some(event);
    }

    /// Trigger a BFS energy pulse from the center.
    pub fn trigger_pulse(&mut self, intensity: f64) {
        let wave = PulseWave {
            frontier: vec![0], // Start from seed crystal (order 0)
            visited: {
                let mut s = HashSet::new();
                s.insert(0);
                s
            },
            birth_tick: self.current_tick,
            intensity: intensity.clamp(0.0, 1.0),
        };
        self.pulse_waves.push(wave);
    }

    /// Advance all BFS pulse waves along the branch graph.
    fn advance_pulses(&mut self) {
        // Clear previous pulse energy
        self.pulse_energy.clear();

        let mut to_remove = Vec::new();

        for (i, wave) in self.pulse_waves.iter_mut().enumerate() {
            let age = self.current_tick.saturating_sub(wave.birth_tick);
            if age > MAX_PULSE_AGE || wave.frontier.is_empty() {
                to_remove.push(i);
                continue;
            }

            // Decay intensity with age
            let decay = 1.0 - (age as f64 / MAX_PULSE_AGE as f64);
            let current_intensity = wave.intensity * decay;

            // Record energy for frontier pixels
            for &order in &wave.frontier {
                let entry = self.pulse_energy.entry(order).or_insert(0.0);
                *entry = (*entry + current_intensity).min(1.0);
            }

            // BFS: expand frontier to children
            let mut new_frontier = Vec::new();
            for &order in &wave.frontier {
                if let Some(children) = self.children_map.get(&order) {
                    for &child in children {
                        if !wave.visited.contains(&child) {
                            wave.visited.insert(child);
                            new_frontier.push(child);
                        }
                    }
                }
                // Also traverse up to parent
                if let Some(idx) = self.order_to_index.get(&order) {
                    if let Some(parent_order) = self.pixels[*idx].parent {
                        if !wave.visited.contains(&parent_order) {
                            wave.visited.insert(parent_order);
                            new_frontier.push(parent_order);
                        }
                    }
                }
            }
            wave.frontier = new_frontier;
        }

        // Remove expired waves (in reverse to preserve indices)
        for i in to_remove.into_iter().rev() {
            self.pulse_waves.remove(i);
        }
    }

    /// Render the growth to a ratatui Canvas with Braille markers.
    /// Fixed 1:1 aspect ratio centered in area. Ambient particles in margins.
    pub fn render(&self, frame: &mut Frame, area: Rect, wall_time: f64, morphs: &SystemMorphs) {
        if area.width < 4 || area.height < 4 {
            return;
        }

        // Braille resolution: 2 dots wide x 4 dots tall per character cell
        let avail_w = area.width as f64 * 2.0;
        let avail_h = area.height as f64 * 4.0;
        let size = avail_w.min(avail_h);

        // Canvas bounds: we map GRID_SIZE to the size
        let scale = size / GRID_SIZE as f64;

        // Canvas coordinate range centered at the midpoint
        let x_mid = GRID_SIZE as f64 / 2.0;
        let y_mid = GRID_SIZE as f64 / 2.0;
        let half_range_x = avail_w / (2.0 * scale);
        let half_range_y = avail_h / (2.0 * scale);

        let growth = GrowthShape {
            pixels: &self.pixels,
            pulse_energy: &self.pulse_energy,
            max_depth: self.max_depth,
            wall_time,
            cpu: morphs.cpu,
        };

        let canvas = Canvas::default()
            .marker(ratatui::symbols::Marker::Braille)
            .x_bounds([x_mid - half_range_x, x_mid + half_range_x])
            .y_bounds([y_mid - half_range_y, y_mid + half_range_y])
            .paint(move |ctx| {
                growth.draw(ctx);
            });

        frame.render_widget(canvas, area);

        // Dim age counter in bottom-right corner
        let age_days = self.age_days();
        if age_days > 0 && area.height > 1 && area.width > 8 {
            let label = format!("day {}", age_days);
            let x = area.x + area.width.saturating_sub(label.len() as u16 + 1);
            let y = area.y + area.height - 1;
            if y < area.y + area.height {
                let span = ratatui::text::Span::styled(
                    label,
                    Style::default().fg(Color::Rgb(60, 60, 60)),
                );
                let paragraph = ratatui::widgets::Paragraph::new(ratatui::text::Line::from(span));
                let label_area = Rect::new(x, y, area.width - (x - area.x), 1);
                frame.render_widget(paragraph, label_area);
            }
        }
    }

    fn age_days(&self) -> u32 {
        if let Ok(created) = chrono::NaiveDateTime::parse_from_str(&self.created_at, "%Y-%m-%dT%H:%M:%SZ") {
            let now = chrono::Utc::now().naive_utc();
            let dur = now.signed_duration_since(created);
            dur.num_days().max(0) as u32
        } else {
            0
        }
    }

    // --- Persistence ---

    pub fn save(&self, path: &Path) -> Result<(), Box<dyn std::error::Error>> {
        let state = SerializedGrowth {
            version: 1,
            seed: self.seed,
            created_at: self.created_at.clone(),
            last_saved: chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string(),
            total_particles: self.pixels.len() as u32,
            pixels: self.pixels.clone(),
        };
        let json = serde_json::to_string_pretty(&state)?;
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        // Atomic write
        let tmp = path.with_extension("tmp");
        std::fs::write(&tmp, &json)?;
        std::fs::rename(&tmp, path)?;
        Ok(())
    }

    pub fn load(path: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        let content = std::fs::read_to_string(path)?;
        let state: SerializedGrowth = serde_json::from_str(&content)?;

        let mut growth = GrowthState {
            grid: vec![false; GRID_SIZE * GRID_SIZE],
            pixels: Vec::new(),
            order_to_index: HashMap::new(),
            children_map: HashMap::new(),
            max_radius: 0.0,
            max_depth: 0,
            seed: state.seed,
            rng: StdRng::seed_from_u64(state.seed),
            pulse_waves: Vec::new(),
            pulse_energy: HashMap::new(),
            current_tick: 0,
            current_morphs: SystemMorphs::default(),
            last_event: None,
            created_at: state.created_at,
            is_fresh: false,
        };

        let cx = (GRID_SIZE / 2) as f64;
        let cy = (GRID_SIZE / 2) as f64;

        for pixel in state.pixels {
            let x = pixel.x as usize;
            let y = pixel.y as usize;
            if x < GRID_SIZE && y < GRID_SIZE {
                growth.grid[y * GRID_SIZE + x] = true;
            }
            growth.order_to_index.insert(pixel.order, growth.pixels.len());
            if let Some(parent) = pixel.parent {
                growth.children_map.entry(parent).or_default().push(pixel.order);
            }
            if pixel.depth > growth.max_depth {
                growth.max_depth = pixel.depth;
            }
            let dx = pixel.x as f64 - cx;
            let dy = pixel.y as f64 - cy;
            let r = (dx * dx + dy * dy).sqrt();
            if r > growth.max_radius {
                growth.max_radius = r;
            }
            growth.pixels.push(pixel);
        }

        Ok(growth)
    }
}

// --- Canvas shape implementation ---

struct GrowthShape<'a> {
    pixels: &'a [Pixel],
    pulse_energy: &'a HashMap<u32, f64>,
    max_depth: u16,
    wall_time: f64,
    cpu: f64,
}

impl<'a> Shape for GrowthShape<'a> {
    fn draw(&self, painter: &mut Painter) {
        for pixel in self.pixels {
            let color = pixel_color(
                pixel.order,
                pixel.depth,
                self.max_depth,
                pixel.model_hash,
                pixel.cache_ratio,
                self.cpu,
                self.wall_time,
                self.pulse_energy.get(&pixel.order).copied().unwrap_or(0.0),
            );
            if let Some((x, y)) = painter.get_point(pixel.x as f64, pixel.y as f64) {
                painter.paint(x, y, color);
            }
        }
    }
}

// Implement draw for Context usage
impl<'a> GrowthShape<'a> {
    fn draw(&self, ctx: &mut Context) {
        for pixel in self.pixels {
            let color = pixel_color(
                pixel.order,
                pixel.depth,
                self.max_depth,
                pixel.model_hash,
                pixel.cache_ratio,
                self.cpu,
                self.wall_time,
                self.pulse_energy.get(&pixel.order).copied().unwrap_or(0.0),
            );
            ctx.draw(&PixelDot {
                x: pixel.x as f64,
                y: pixel.y as f64,
                color,
            });
        }
    }
}

struct PixelDot {
    x: f64,
    y: f64,
    color: Color,
}

impl Shape for PixelDot {
    fn draw(&self, painter: &mut Painter) {
        if let Some((x, y)) = painter.get_point(self.x, self.y) {
            painter.paint(x, y, self.color);
        }
    }
}

/// Pure math color computation. No match statements on model names.
fn pixel_color(
    pixel_order: u32,
    depth: u16,
    max_depth: u16,
    model_hash: f64,
    cache_ratio: f64,
    cpu: f64,
    wall_time: f64,
    pulse_energy: f64,
) -> Color {
    let d = depth as f64 / max_depth.max(1) as f64; // 0=center, 1=tip

    // Hue: model_hash places it on the color wheel continuously
    let hue = (model_hash * 360.0 + d * 40.0 * PI.sin()) % 360.0;

    // Saturation: depth-driven, cache makes it more crystalline (lower sat = more white)
    let sat = (0.4 + 0.4 * d - cache_ratio * 0.25).clamp(0.1, 0.95);

    // Value (brightness):
    let base_v = 0.2 + 0.35 * d;

    // Breathing: CPU drives metabolism speed, pi-based phase
    let breath = 0.1 * (wall_time * (1.0 + cpu * 2.0) + d * PI * 0.5).sin();

    // Energy pulse: bright flash traveling through branches
    let pulse = pulse_energy * 0.5;

    // Cache shimmer: high-frequency sparkle on cache-efficient branches
    let shimmer = cache_ratio * 0.08 * (wall_time * PI + pixel_order as f64 * 0.1).sin();

    let val = (base_v + breath + pulse + shimmer).clamp(0.0, 1.0);

    hsv_to_rgb(hue, sat, val)
}

// --- Serialization ---

#[derive(Serialize, Deserialize)]
struct SerializedGrowth {
    version: u32,
    seed: u64,
    created_at: String,
    last_saved: String,
    total_particles: u32,
    pixels: Vec<Pixel>,
}

// --- Export / Import ---

pub fn export_state(dest: &Path) -> Result<GrowthInfo, Box<dyn std::error::Error>> {
    let src = crate::paths::growth_state_file()
        .ok_or("No home directory")?;
    let state = GrowthState::load(&src)?;
    state.save(dest)?;
    Ok(GrowthInfo {
        total_particles: state.pixels.len() as u32,
        age_days: state.age_days(),
        created_at: state.created_at.clone(),
    })
}

pub fn import_state(src: &Path) -> Result<GrowthInfo, Box<dyn std::error::Error>> {
    let state = GrowthState::load(src)?;
    let dest = crate::paths::growth_state_file()
        .ok_or("No home directory")?;
    state.save(&dest)?;
    Ok(GrowthInfo {
        total_particles: state.pixels.len() as u32,
        age_days: state.age_days(),
        created_at: state.created_at.clone(),
    })
}

/// Load or create growth state. If fresh, do a birth burst.
pub fn load_or_create() -> GrowthState {
    if let Some(path) = crate::paths::growth_state_file() {
        if path.exists() {
            if let Ok(state) = GrowthState::load(&path) {
                return state;
            }
        }
    }

    // Fresh: use username hash as seed
    let username = whoami();
    let seed = hash_to_u64(&username);
    let mut state = GrowthState::new(seed);
    state.grow_batch(BIRTH_BURST);
    state
}

fn whoami() -> String {
    std::env::var("USERNAME")
        .or_else(|_| std::env::var("USER"))
        .unwrap_or_else(|_| "luna".to_string())
}

fn hash_to_u64(s: &str) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for byte in s.bytes() {
        h ^= byte as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}
