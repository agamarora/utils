use std::collections::{HashMap, VecDeque};
use sysinfo::{System, Networks, Disks, Components};

const MAX_CPU_HISTORY: usize = 300;
const MAX_NET_HISTORY: usize = 30;

#[derive(Debug, Clone)]
pub struct DiskInfo {
    pub name: String,
    pub mount: String,
    pub total_gb: f64,
    pub used_gb: f64,
    pub pct: f64,
}

#[derive(Debug, Clone)]
pub struct DiskIO {
    pub name: String,
    pub read_bps: f64,
    pub write_bps: f64,
    pub active_pct: f64,
}

#[derive(Debug, Clone)]
pub struct ProcessInfo {
    pub pid: u32,
    pub name: String,
    pub cpu_pct: f32,
    pub mem_mb: f64,
    pub is_claude: bool,
}

#[derive(Debug, Clone)]
pub struct TempReading {
    pub label: String,
    pub celsius: f32,
}

pub struct SystemCollector {
    sys: System,
    networks: Networks,
    disks: Disks,
    components: Components,
    cpu_history: VecDeque<f32>,
    net_prev: (u64, u64),
    net_history: VecDeque<(f64, f64)>,
    net_peak: (f64, f64),
    disk_io_prev: HashMap<String, (u64, u64)>,
    last_tick: std::time::Instant,
}

impl SystemCollector {
    pub fn new() -> Self {
        let mut sys = System::new_all();
        sys.refresh_cpu_usage();
        let networks = Networks::new_with_refreshed_list();
        let disks = Disks::new_with_refreshed_list();
        let components = Components::new_with_refreshed_list();

        // Compute initial net bytes
        let mut rx_total = 0u64;
        let mut tx_total = 0u64;
        for (_name, data) in &networks {
            rx_total += data.total_received();
            tx_total += data.total_transmitted();
        }

        Self {
            sys,
            networks,
            disks,
            components,
            cpu_history: VecDeque::with_capacity(MAX_CPU_HISTORY),
            net_prev: (rx_total, tx_total),
            net_history: VecDeque::with_capacity(MAX_NET_HISTORY),
            net_peak: (0.0, 0.0),
            disk_io_prev: HashMap::new(),
            last_tick: std::time::Instant::now(),
        }
    }

    pub fn tick(&mut self) {
        let elapsed = self.last_tick.elapsed().as_secs_f64();
        self.last_tick = std::time::Instant::now();

        self.sys.refresh_cpu_usage();
        self.sys.refresh_memory();
        self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All, true);

        // CPU history
        let cpu_pct = self.sys.global_cpu_usage();
        self.cpu_history.push_back(cpu_pct);
        if self.cpu_history.len() > MAX_CPU_HISTORY {
            self.cpu_history.pop_front();
        }

        // Network deltas
        self.networks.refresh();
        let mut rx_total = 0u64;
        let mut tx_total = 0u64;
        for (_name, data) in &self.networks {
            rx_total += data.total_received();
            tx_total += data.total_transmitted();
        }

        if elapsed > 0.0 {
            let rx_delta = rx_total.saturating_sub(self.net_prev.0);
            let tx_delta = tx_total.saturating_sub(self.net_prev.1);
            let rx_mbps = (rx_delta as f64 * 8.0) / (elapsed * 1_000_000.0);
            let tx_mbps = (tx_delta as f64 * 8.0) / (elapsed * 1_000_000.0);

            self.net_history.push_back((rx_mbps, tx_mbps));
            if self.net_history.len() > MAX_NET_HISTORY {
                self.net_history.pop_front();
            }
            if rx_mbps > self.net_peak.0 {
                self.net_peak.0 = rx_mbps;
            }
            if tx_mbps > self.net_peak.1 {
                self.net_peak.1 = tx_mbps;
            }
        }
        self.net_prev = (rx_total, tx_total);

        // Refresh disks and components
        self.disks.refresh();
        self.components.refresh();
    }

    pub fn cpu_percent(&self) -> f32 {
        self.sys.global_cpu_usage()
    }

    pub fn cpu_history(&self) -> &VecDeque<f32> {
        &self.cpu_history
    }

    /// Average CPU % over last 5 minutes (150 entries at 2s tick).
    /// Returns None if no history yet.
    pub fn cpu_avg_5min(&self) -> Option<f32> {
        if self.cpu_history.is_empty() {
            return None;
        }
        let count = self.cpu_history.len().min(150);
        let start = self.cpu_history.len() - count;
        let sum: f32 = self.cpu_history.iter().skip(start).sum();
        Some(sum / count as f32)
    }

    pub fn cpu_freq_mhz(&self) -> u64 {
        self.sys.cpus().first().map(|c| c.frequency()).unwrap_or(0)
    }

    pub fn memory_used_total(&self) -> (u64, u64) {
        (self.sys.used_memory(), self.sys.total_memory())
    }

    pub fn swap_used_total(&self) -> (u64, u64) {
        (self.sys.used_swap(), self.sys.total_swap())
    }

    /// Returns (rx_now, tx_now, rx_avg, tx_avg, rx_peak, tx_peak) in Mbps
    pub fn net_speeds(&self) -> (f64, f64, f64, f64, f64, f64) {
        let (rx_now, tx_now) = self.net_history.back().copied().unwrap_or((0.0, 0.0));
        let (rx_avg, tx_avg) = if self.net_history.is_empty() {
            (0.0, 0.0)
        } else {
            let (rx_sum, tx_sum) = self.net_history.iter().fold((0.0, 0.0), |(ra, ta), (r, t)| (ra + r, ta + t));
            let n = self.net_history.len() as f64;
            (rx_sum / n, tx_sum / n)
        };
        (rx_now, tx_now, rx_avg, tx_avg, self.net_peak.0, self.net_peak.1)
    }

    pub fn disk_usage(&self) -> Vec<DiskInfo> {
        self.disks.iter().map(|d| {
            let total = d.total_space();
            let available = d.available_space();
            let used = total.saturating_sub(available);
            let total_gb = total as f64 / (1024.0 * 1024.0 * 1024.0);
            let used_gb = used as f64 / (1024.0 * 1024.0 * 1024.0);
            let pct = if total > 0 { (used as f64 / total as f64) * 100.0 } else { 0.0 };
            DiskInfo {
                name: d.name().to_string_lossy().to_string(),
                mount: d.mount_point().to_string_lossy().to_string(),
                total_gb,
                used_gb,
                pct,
            }
        }).collect()
    }

    pub fn disk_io(&self, active_pct: &std::collections::HashMap<String, f64>) -> Vec<DiskIO> {
        // Compute I/O speed from sysinfo disk data + PDH active %
        // sysinfo doesn't expose per-disk I/O bytes directly on all platforms
        // We use the PDH active % from platform_win and show R/W from our tracking
        let mut result = Vec::new();
        for disk in self.disks.iter() {
            let mount = disk.mount_point().to_string_lossy().to_string();
            let name = disk.name().to_string_lossy().to_string();

            let active = active_pct.get(&mount)
                .or_else(|| active_pct.get(&name))
                .copied()
                .unwrap_or(0.0);

            // Get I/O speeds from our tracking
            let (read_bps, write_bps) = self.disk_io_prev
                .get(&mount)
                .or_else(|| self.disk_io_prev.get(&name))
                .copied()
                .unwrap_or((0, 0));

            result.push(DiskIO {
                name: mount,
                read_bps: read_bps as f64,
                write_bps: write_bps as f64,
                active_pct: active,
            });
        }
        result
    }

    /// Returns (top_by_cpu, top_by_mem)
    pub fn top_processes(&self, n: usize) -> (Vec<ProcessInfo>, Vec<ProcessInfo>) {
        let mut procs: Vec<ProcessInfo> = self.sys.processes().iter().map(|(pid, p)| {
            let name = p.name().to_string_lossy().to_string();
            let cmd_str = p.cmd().iter().map(|s| s.to_string_lossy().to_string()).collect::<Vec<_>>().join(" ");
            let is_claude = name.to_lowercase().contains("claude")
                || cmd_str.to_lowercase().contains("claude")
                || cmd_str.contains("@anthropic");
            ProcessInfo {
                pid: pid.as_u32(),
                name,
                cpu_pct: p.cpu_usage(),
                mem_mb: p.memory() as f64 / (1024.0 * 1024.0),
                is_claude,
            }
        }).collect();

        let mut by_cpu = procs.clone();
        by_cpu.sort_by(|a, b| b.cpu_pct.partial_cmp(&a.cpu_pct).unwrap_or(std::cmp::Ordering::Equal));
        by_cpu.truncate(n);

        procs.sort_by(|a, b| b.mem_mb.partial_cmp(&a.mem_mb).unwrap_or(std::cmp::Ordering::Equal));
        procs.truncate(n);

        (by_cpu, procs)
    }

    pub fn temperatures(&self) -> Vec<TempReading> {
        self.components.iter().map(|c| {
            TempReading {
                label: c.label().to_string(),
                celsius: c.temperature(),
            }
        }).collect()
    }
}
