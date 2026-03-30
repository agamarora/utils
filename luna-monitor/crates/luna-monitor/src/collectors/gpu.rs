#[derive(Debug, Clone)]
pub struct GpuData {
    pub name: String,
    pub utilization_pct: u32,
    pub vram_used_mb: u64,
    pub vram_total_mb: u64,
    pub temp_celsius: u32,
}

#[cfg(feature = "gpu")]
pub struct GpuCollector {
    nvml: nvml_wrapper::Nvml,
    device_index: u32,
}

#[cfg(feature = "gpu")]
impl GpuCollector {
    pub fn try_init() -> Option<Self> {
        let nvml = nvml_wrapper::Nvml::init().ok()?;
        let _ = nvml.device_by_index(0).ok()?;
        Some(Self { nvml, device_index: 0 })
    }

    pub fn collect(&self) -> Option<GpuData> {
        let device = self.nvml.device_by_index(self.device_index).ok()?;
        let name = device.name().ok()?;
        let util = device.utilization_rates().ok()?;
        let mem = device.memory_info().ok()?;
        let temp = device.temperature(nvml_wrapper::enum_wrappers::device::TemperatureSensor::Gpu).ok()?;

        Some(GpuData {
            name,
            utilization_pct: util.gpu,
            vram_used_mb: mem.used / (1024 * 1024),
            vram_total_mb: mem.total / (1024 * 1024),
            temp_celsius: temp,
        })
    }

    /// Try LHM fallback if nvml collect fails
    pub fn collect_or_lhm(&self) -> Option<GpuData> {
        self.collect().or_else(|| crate::collectors::lhm::fetch().and_then(|d| d.gpu))
    }
}

#[cfg(not(feature = "gpu"))]
pub struct GpuCollector;

#[cfg(not(feature = "gpu"))]
impl GpuCollector {
    pub fn try_init() -> Option<Self> {
        // No nvml — return struct, will use LHM fallback
        Some(GpuCollector)
    }

    pub fn collect(&self) -> Option<GpuData> {
        // Try LHM
        crate::collectors::lhm::fetch().and_then(|d| d.gpu)
    }
}
