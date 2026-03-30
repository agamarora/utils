use crate::types::SystemMorphs;
use sysinfo::{System, Networks, Disks};
use std::time::Instant;

#[cfg(windows)]
use std::collections::HashMap;
#[cfg(windows)]
use std::ffi::c_void;

// --- PDH FFI (Windows only) ---

#[cfg(windows)]
static mut PDH_QUERY: *mut c_void = std::ptr::null_mut();

#[cfg(windows)]
static mut PDH_COUNTERS: Option<HashMap<String, *mut c_void>> = None;

#[cfg(windows)]
#[repr(C)]
struct PdhFmtCounterValue {
    c_status: u32,
    double_value: f64,
}

#[cfg(windows)]
const PDH_FMT_DOUBLE: u32 = 0x00000200;

#[cfg(windows)]
extern "system" {
    fn PdhOpenQueryW(
        szDataSource: *const u16,
        dwUserData: usize,
        phQuery: *mut *mut c_void,
    ) -> i32;
    fn PdhAddCounterW(
        hQuery: *mut c_void,
        szFullCounterPath: *const u16,
        dwUserData: usize,
        phCounter: *mut *mut c_void,
    ) -> i32;
    fn PdhCollectQueryData(hQuery: *mut c_void) -> i32;
    fn PdhGetFormattedCounterValue(
        hCounter: *mut c_void,
        dwFormat: u32,
        lpdwType: *mut u32,
        pValue: *mut PdhFmtCounterValue,
    ) -> i32;
    fn PdhCloseQuery(hQuery: *mut c_void) -> i32;
}

#[cfg(windows)]
#[allow(static_mut_refs)]
fn init_pdh(drives: &[String]) {
    unsafe {
        let mut probe_query: *mut c_void = std::ptr::null_mut();
        if PdhOpenQueryW(std::ptr::null(), 0, &mut probe_query) != 0 {
            return;
        }

        let mut probe_counters: Vec<(String, u32, *mut c_void)> = Vec::new();
        for drive in drives {
            let letter = drive.chars().next().unwrap_or('C');
            for disk_num in 0..4u32 {
                let path = format!("\\PhysicalDisk({} {}:)\\% Disk Time", disk_num, letter);
                let wide: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
                let mut hc: *mut c_void = std::ptr::null_mut();
                if PdhAddCounterW(probe_query, wide.as_ptr(), 0, &mut hc) == 0 {
                    probe_counters.push((drive.clone(), disk_num, hc));
                }
            }
        }

        if probe_counters.is_empty() {
            PdhCloseQuery(probe_query);
            return;
        }

        PdhCollectQueryData(probe_query);
        std::thread::sleep(std::time::Duration::from_millis(100));
        PdhCollectQueryData(probe_query);

        let mut confirmed: HashMap<String, u32> = HashMap::new();
        for (drive, disk_num, hc) in &probe_counters {
            let mut val = PdhFmtCounterValue {
                c_status: 0,
                double_value: 0.0,
            };
            let result = PdhGetFormattedCounterValue(*hc, PDH_FMT_DOUBLE, std::ptr::null_mut(), &mut val);
            if result == 0 && val.c_status == 0 {
                confirmed.entry(drive.clone()).or_insert(*disk_num);
            }
        }

        PdhCloseQuery(probe_query);

        let mut real_query: *mut c_void = std::ptr::null_mut();
        if PdhOpenQueryW(std::ptr::null(), 0, &mut real_query) != 0 {
            return;
        }

        let mut real_counters = HashMap::new();
        for (drive, disk_num) in &confirmed {
            let letter = drive.chars().next().unwrap_or('C');
            let path = format!("\\PhysicalDisk({} {}:)\\% Disk Time", disk_num, letter);
            let wide: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
            let mut hc: *mut c_void = std::ptr::null_mut();
            if PdhAddCounterW(real_query, wide.as_ptr(), 0, &mut hc) == 0 {
                real_counters.insert(drive.clone(), hc);
            }
        }

        PdhCollectQueryData(real_query);
        PDH_QUERY = real_query;
        PDH_COUNTERS = Some(real_counters);
    }
}

#[cfg(windows)]
#[allow(static_mut_refs)]
fn collect_disk_active() -> HashMap<String, f64> {
    let mut result = HashMap::new();
    unsafe {
        if PDH_QUERY.is_null() {
            return result;
        }
        let counters = match PDH_COUNTERS.as_ref() {
            Some(c) => c,
            None => return result,
        };
        PdhCollectQueryData(PDH_QUERY);
        for (drive, hc) in counters {
            let mut val = PdhFmtCounterValue {
                c_status: 0,
                double_value: 0.0,
            };
            if PdhGetFormattedCounterValue(*hc, PDH_FMT_DOUBLE, std::ptr::null_mut(), &mut val) == 0 {
                let pct = val.double_value.clamp(0.0, 100.0);
                result.insert(drive.clone(), pct);
            }
        }
    }
    result
}

pub struct SystemCollector {
    sys: System,
    networks: Networks,
    disks: Disks,
    net_prev: (u64, u64),
    net_bytes_sec: f64,
    last_tick: Instant,
    #[cfg(windows)]
    pdh_initialized: bool,
}

impl SystemCollector {
    pub fn new() -> Self {
        let mut sys = System::new_all();
        sys.refresh_cpu_usage();
        let networks = Networks::new_with_refreshed_list();
        let disks = Disks::new_with_refreshed_list();

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
            net_prev: (rx_total, tx_total),
            net_bytes_sec: 0.0,
            last_tick: Instant::now(),
            #[cfg(windows)]
            pdh_initialized: false,
        }
    }

    /// Refresh all data. Call every ~2 seconds.
    pub fn tick(&mut self) {
        let elapsed = self.last_tick.elapsed().as_secs_f64();
        self.last_tick = Instant::now();

        self.sys.refresh_cpu_usage();
        self.sys.refresh_memory();
        self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All, true);
        self.networks.refresh();
        self.disks.refresh();

        // Init PDH on first tick (needs disk list)
        #[cfg(windows)]
        {
            if !self.pdh_initialized {
                let drives: Vec<String> = self.disks.iter()
                    .map(|d| d.mount_point().to_string_lossy().to_string())
                    .collect();
                init_pdh(&drives);
                self.pdh_initialized = true;
            }
        }

        // Network bytes/sec
        let mut rx_total = 0u64;
        let mut tx_total = 0u64;
        for (_name, data) in &self.networks {
            rx_total += data.total_received();
            tx_total += data.total_transmitted();
        }

        if elapsed > 0.0 {
            let rx_delta = rx_total.saturating_sub(self.net_prev.0);
            let tx_delta = tx_total.saturating_sub(self.net_prev.1);
            self.net_bytes_sec = (rx_delta + tx_delta) as f64 / elapsed;
        }
        self.net_prev = (rx_total, tx_total);
    }

    /// Aggregate CPU percent (0-100).
    pub fn cpu_pct(&self) -> f64 {
        self.sys.global_cpu_usage() as f64
    }

    /// RAM usage percent (0-100).
    pub fn ram_pct(&self) -> f64 {
        let total = self.sys.total_memory();
        let used = self.sys.used_memory();
        if total == 0 { 0.0 } else { (used as f64 / total as f64) * 100.0 }
    }

    /// Weighted average disk active percent (0-100). Uses PDH on Windows.
    pub fn disk_active_pct(&self) -> f64 {
        #[cfg(windows)]
        {
            let active = collect_disk_active();
            if active.is_empty() {
                return 0.0;
            }
            let sum: f64 = active.values().sum();
            sum / active.len() as f64
        }
        #[cfg(not(windows))]
        {
            0.0 // PDH not available on non-Windows
        }
    }

    /// Network bytes/sec (total rx+tx).
    pub fn net_bytes_sec(&self) -> f64 {
        self.net_bytes_sec
    }

    /// Top N processes by CPU usage. Returns (pid, name, cpu_pct).
    pub fn top_processes(&self, n: usize) -> Vec<(u32, String, f32)> {
        let mut procs: Vec<(u32, String, f32)> = self.sys.processes().iter()
            .map(|(pid, p)| {
                (pid.as_u32(), p.name().to_string_lossy().to_string(), p.cpu_usage())
            })
            .collect();
        procs.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal));
        procs.truncate(n);
        procs
    }

    /// Returns SystemMorphs with all values normalized 0.0-1.0.
    pub fn morphs(&self) -> SystemMorphs {
        SystemMorphs {
            cpu: (self.cpu_pct() / 100.0).clamp(0.0, 1.0),
            ram: (self.ram_pct() / 100.0).clamp(0.0, 1.0),
            disk_active: (self.disk_active_pct() / 100.0).clamp(0.0, 1.0),
            net_bytes_sec: (self.net_bytes_sec() / 10_000_000.0).min(1.0),
        }
    }
}
