//! Windows-specific platform code: PDH disk active % counters.
//! Uses ctypes-style FFI (same approach as Python version).
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
}

#[cfg(windows)]
#[repr(C)]
struct PdhFmtCounterValue {
    c_status: u32,
    double_value: f64,
}

#[cfg(windows)]
const PDH_FMT_DOUBLE: u32 = 0x00000200;

/// Initialize PDH counters for disk active time. Call once at startup.
#[cfg(windows)]
pub fn init_pdh(drives: &[String]) {
    unsafe {
        let mut query: *mut c_void = std::ptr::null_mut();
        if PdhOpenQueryW(std::ptr::null(), 0, &mut query) != 0 {
            return;
        }
        PDH_QUERY = query;

        let mut counters = HashMap::new();

        for drive in drives {
            let letter = drive.chars().next().unwrap_or('C');
            // Try common physical disk indices
            for disk_num in 0..4 {
                let path = format!("\\PhysicalDisk({} {}:)\\% Disk Time", disk_num, letter);
                let wide: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
                let mut hc: *mut c_void = std::ptr::null_mut();
                if PdhAddCounterW(query, wide.as_ptr(), 0, &mut hc) == 0 {
                    counters.insert(drive.clone(), hc);
                    break;
                }
            }
        }

        // Prime first sample
        PdhCollectQueryData(query);
        PDH_COUNTERS = Some(counters);
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
