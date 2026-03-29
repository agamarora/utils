"""GPU metrics collection via NVIDIA NVML (optional dependency)."""

GPU_AVAILABLE = False
_GPU_HANDLE = None
GPU_NAME = "GPU"

try:
    import pynvml

    pynvml.nvmlInit()
    _GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    _raw_name = pynvml.nvmlDeviceGetName(_GPU_HANDLE)
    GPU_NAME = (_raw_name.decode() if isinstance(_raw_name, bytes) else _raw_name)
    GPU_NAME = GPU_NAME.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")
    GPU_AVAILABLE = True
except Exception:
    pass


def collect_gpu() -> dict | None:
    """Collect GPU metrics. Returns dict or None if unavailable.

    Returns:
        {"pct": float, "mem_used": int, "mem_total": int, "temp": int} or None
    """
    if not GPU_AVAILABLE or _GPU_HANDLE is None:
        return None
    try:
        import pynvml

        u = pynvml.nvmlDeviceGetUtilizationRates(_GPU_HANDLE)
        mem = pynvml.nvmlDeviceGetMemoryInfo(_GPU_HANDLE)
        temp = pynvml.nvmlDeviceGetTemperature(
            _GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU
        )
        return {
            "pct": u.gpu,
            "mem_used": mem.used,
            "mem_total": mem.total,
            "temp": temp,
        }
    except Exception:
        return None
