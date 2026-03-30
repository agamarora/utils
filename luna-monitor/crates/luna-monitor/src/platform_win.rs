//! Windows-specific platform code: PDH disk active % counters.
//! Two-query probe approach: probe all (drive, disk_num) combos,
//! find which ones return real data, then build a real query with only those.
#![allow(static_mut_refs)]

#[cfg(windows)]
use std::collections::HashMap;

#[cfg(windows)]
use std::ffi::c_void;

#[cfg(windows)]
static mut PDH_QUERY: *mut c_void = std::ptr::null_mut();

#[cfg(windows)]
static mut PDH_COUNTERS: Option<HashMap<String, *mut c_void>> = None;

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
#[repr(C)]
struct PdhFmtCounterValue {
    c_status: u32,
    double_value: f64,
}

#[cfg(windows)]
const PDH_FMT_DOUBLE: u32 = 0x00000200;

/// Initialize PDH counters for disk active time using two-query probe.
/// Phase 1: open probe query, add all combos, collect twice, find working ones.
/// Phase 2: close probe, open real query with only confirmed counters.
#[cfg(windows)]
pub fn init_pdh(drives: &[String]) {
    unsafe {
        // Phase 1: Probe query
        let mut probe_query: *mut c_void = std::ptr::null_mut();
        if PdhOpenQueryW(std::ptr::null(), 0, &mut probe_query) != 0 {
            return;
        }

        // Add all (drive, disk_num) combinations
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

        // PDH rate counters need 2 collections to produce data
        PdhCollectQueryData(probe_query);
        std::thread::sleep(std::time::Duration::from_millis(100));
        PdhCollectQueryData(probe_query);

        // Read all counters, find which (drive, disk_num) pairs actually work
        let mut confirmed: HashMap<String, u32> = HashMap::new();
        for (drive, disk_num, hc) in &probe_counters {
            let mut val = PdhFmtCounterValue {
                c_status: 0,
                double_value: 0.0,
            };
            let result = PdhGetFormattedCounterValue(*hc, PDH_FMT_DOUBLE, std::ptr::null_mut(), &mut val);
            if result == 0 && val.c_status == 0 {
                // This counter works — keep the first confirmed one per drive
                confirmed.entry(drive.clone()).or_insert(*disk_num);
            }
        }

        // Close probe query entirely
        PdhCloseQuery(probe_query);

        // Phase 2: Build real query with only confirmed counters
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

        // Prime the real query
        PdhCollectQueryData(real_query);
        PDH_QUERY = real_query;
        PDH_COUNTERS = Some(real_counters);
    }
}

/// Collect disk active-time % via PDH. Returns {drive: pct}.
#[cfg(windows)]
pub fn collect_disk_active() -> HashMap<String, f64> {
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

/// Stub for non-Windows platforms.
#[cfg(not(windows))]
pub fn init_pdh(_drives: &[String]) {}

/// Stub for non-Windows platforms.
#[cfg(not(windows))]
pub fn collect_disk_active() -> std::collections::HashMap<String, f64> {
    std::collections::HashMap::new()
}
